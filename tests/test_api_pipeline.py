from __future__ import annotations

from pathlib import Path
import json

from fastapi.testclient import TestClient

from sunshine_api.main import app
from sunshine_api.services.model_usage import _model_usage_report, _read_model_usage_artifact


def test_api_pipeline_run_file_processes_one_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_EMBEDDING_PROVIDER", "placeholder")
    source = tmp_path / "tea.txt"
    source.write_text("Annual Sunshine Tea guest list and event notes.", encoding="utf-8")
    output_dir = tmp_path / "api-out"
    checkpoint_path = tmp_path / "api-checkpoints.sqlite"

    response = TestClient(app).post(
        "/admin/pipeline/run-file",
        json={
            "input_file": str(source),
            "output_dir": str(output_dir),
            "source_path": "/source/tea.txt",
            "relative_path": "Sunshine shared folders/Teas/tea.txt",
            "checkpoint_path": str(checkpoint_path),
            "thread_id": "api-test-thread",
            "retry_attempts": 2,
            "enable_llm_tags": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["final_result"]["route_status"] == "route_candidate"
    assert payload["final_result"]["top_tag_candidate"] == "annual_spring_tea"
    assert payload["graph_result_path"] == str(output_dir / "graph-result.json")
    assert payload["graph_audit_events_path"] == str(output_dir / "graph-audit-events.jsonl")
    assert Path(payload["graph_result_path"]).exists()
    assert Path(payload["graph_audit_events_path"]).exists()
    assert checkpoint_path.exists()


def test_local_infrastructure_status_is_local_only(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://sunshine:local@localhost:5432/sunshine_club")
    monkeypatch.setenv("SUNSHINE_QDRANT_URL", "http://127.0.0.1:6333")
    monkeypatch.setenv("CORTEX_OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("CORTEX_MODEL", "gemma4-26b")

    response = TestClient(app).get("/admin/system/local-infrastructure")

    assert response.status_code == 200
    payload = response.json()
    assert payload["local_only"] is True
    assert payload["policy"]["hosted_third_party_apis_allowed"] is False
    assert payload["policy"]["source_files_mutable"] is False
    assert payload["postgres"]["configured"] is True
    assert payload["qdrant"]["provider"] == "qdrant"
    assert payload["qdrant"]["local_only"] is True
    assert payload["docling"]["provider"] == "docling"
    assert payload["docling"]["local_only"] is True
    assert payload["cortex"]["configured"] is True


def test_run_request_rejects_hosted_openai_provider(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_REVIEW_DB_PATH", str(tmp_path / "review.sqlite"))

    response = TestClient(app).post(
        "/admin/runs",
        json={
            "preset_key": "qa_samples_fast",
            "input_root": str(tmp_path / "input"),
            "output_dir": str(tmp_path / "output"),
            "embedding_provider": "openai",
            "start": False,
        },
    )

    assert response.status_code == 422


def test_provider_benchmark_api_runs_current_provider(tmp_path: Path) -> None:
    source = tmp_path / "minutes.txt"
    source.write_text("Meeting minutes and Sunshine Club notes.", encoding="utf-8")
    output_dir = tmp_path / "provider-benchmark"
    client = TestClient(app)

    run = client.post(
        "/admin/provider-benchmarks/run",
        json={"paths": [str(source)], "providers": ["current"], "output_dir": str(output_dir)},
    )
    latest = client.get("/admin/provider-benchmarks/latest", params={"output_dir": str(output_dir)})

    assert run.status_code == 200
    assert run.json()["summary"]["by_provider"]["current"] == 1
    assert run.json()["summary"]["local_only"] is True
    assert latest.status_code == 200
    assert latest.json()["summary"]["result_count"] == 1
    assert latest.json()["results"][0]["provider"] == "current"


def test_model_usage_report_infers_calls_from_legacy_artifacts(tmp_path: Path) -> None:
    output_dir = tmp_path / "legacy-run"
    output_dir.mkdir()
    (output_dir / "sample-pipeline-results.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/scan.pdf",
                "relative_path": "Scans/scan.pdf",
                "warnings": ["ocr_fallback_used:openai:gpt-4.1-mini"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "sample-llm-tag-inspections.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/scan.pdf",
                "relative_path": "Scans/scan.pdf",
                "provider": "cortex",
                "model": "gemma4-26b",
                "llm_status": "inspected",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "sample-embeddings.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/scan.pdf",
                "relative_path": "Scans/scan.pdf",
                "chunk_id": "scan:1",
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-3-large",
                "embedding_status": "embedded",
                "embedding_dimensions": 3072,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    rows = _read_model_usage_artifact(output_dir, run_id=123)
    report = _model_usage_report(rows)

    assert report["summary"]["total_calls"] == 3
    assert report["summary"]["external_calls"] == 2
    assert report["summary"]["local_calls"] == 1
    assert report["summary"]["unknown_cost_basis_calls"] == 0
    assert report["summary"]["cost_basis_completeness_rate"] == 1.0
    assert report["summary"]["unknown_external_cost_calls"] == 2
    assert report["by_purpose"]["ocr_fallback"]["calls"] == 1
    assert report["by_purpose"]["tag_inspection"]["calls"] == 1
    assert report["by_purpose"]["chunk_embedding"]["calls"] == 1


def test_run_report_reads_live_graph_run_artifacts_before_batch_finalize(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_REVIEW_DB_PATH", str(tmp_path / "review.sqlite"))
    output_dir = tmp_path / "live-run"
    first_run_dir = output_dir / "graph-runs" / "00001"
    second_run_dir = output_dir / "graph-runs" / "00002"
    first_run_dir.mkdir(parents=True)
    second_run_dir.mkdir(parents=True)
    accepted = {
        "sample_path": str(tmp_path / "accepted.pdf"),
        "source_path": "/source/accepted.pdf",
        "relative_path": "Accepted/accepted.pdf",
        "route_status": "route_candidate",
        "final_class": "document",
        "extraction_strategy": "text_extraction",
        "extraction_status": "extracted",
        "quality": "ok",
        "top_tag_candidate": "meeting_records",
        "secondary_tags": ["meeting_minutes"],
        "tag_confidence": 0.96,
        "placement_status": "ready",
    }
    review_required = {
        "sample_path": str(tmp_path / "review.pdf"),
        "source_path": "/source/review.pdf",
        "relative_path": "Review/review.pdf",
        "route_status": "review_ocr_quality",
        "review_reason": "ocr_quality_not_trusted",
        "final_class": "scanned_document",
        "extraction_strategy": "ocr_page_level",
        "extraction_status": "extracted",
        "quality": "poor",
        "top_tag_candidate": "scrapbooks",
        "secondary_tags": ["scrapbook_page"],
        "tag_confidence": 0.64,
        "placement_status": "needs_review",
        "warnings": ["ocr_fallback_used:openai:gpt-4.1-mini"],
    }
    (first_run_dir / "sample-pipeline-results.jsonl").write_text(json.dumps(accepted) + "\n", encoding="utf-8")
    (second_run_dir / "sample-pipeline-results.jsonl").write_text(json.dumps(review_required) + "\n", encoding="utf-8")
    (second_run_dir / "sample-review-queue.jsonl").write_text(json.dumps(review_required) + "\n", encoding="utf-8")
    (second_run_dir / "sample-ocr-documents.jsonl").write_text(
        json.dumps({**review_required, "total_text_length": 42, "mean_confidence": 52.0}) + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-ocr-pages.jsonl").write_text(
        json.dumps({**review_required, "page_number": 1, "ocr_status": "ok"}) + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-extraction-results.jsonl").write_text(
        json.dumps({**review_required, "text": "Live OCR text snippet."}) + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-model-usage.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "purpose": "ocr_fallback",
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "status": "ok",
                "cost_basis": "external",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-provider-attempts.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "provider": "current",
                "capability": "extraction",
                "status": "extracted",
                "strategy": "ocr_page_level",
                "seconds": 0.5,
                "warnings": [],
                "metadata": {"local_only": True},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-source-identity.jsonl").write_text(
        json.dumps(
            {
                "file_id": "file-review",
                "content_sha256": "a" * 64,
                "size_bytes": 123,
                "modified_at_ns": 1000,
                "extension": ".pdf",
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "sample_path": str(second_run_dir / "review.pdf"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-file-probes.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "sample_path": str(second_run_dir / "review.pdf"),
                "provider": "native",
                "status": "probed",
                "mime_type": "application/pdf",
                "extension": ".pdf",
                "media_type": "pdf",
                "size_bytes": 123,
                "page_count": 12,
                "embedded_text_chars": 0,
                "image_only_pdf_likelihood": 0.95,
                "encrypted": False,
                "width": None,
                "height": None,
                "warnings": [],
                "metadata": {"local_only": True},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-provider-selections.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "sample_path": str(second_run_dir / "review.pdf"),
                "selected_provider": "current",
                "provider_chain": ["docling", "cortex_ocr", "current"],
                "provider_selection_reason": "preferred_docling_unavailable_fell_back_to_configured",
                "preferred_provider": "docling",
                "configured_provider": "current",
                "local_only_required": True,
                "skipped_providers": [{"provider": "docling", "reason": "dependency_unavailable"}],
                "metadata": {"strategy": "ocr_page_level", "media_type": "pdf"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-document-segments.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "segment_id": "review:1:segment-001",
                "page_start": 1,
                "page_end": 12,
                "segment_index": 1,
                "segment_type": "scrapbook_page_group",
                "segment_confidence": 0.55,
                "requires_segment_review": True,
                "segment_boundary_evidence": ["matched:scrapbook"],
                "metadata": {"policy": "conservative_single_segment"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-indexing.jsonl").write_text(
        json.dumps(
            {
                "provider": "noop",
                "collection": None,
                "status": "skipped",
                "indexed_count": 0,
                "skipped_count": 1,
                "semantic_embedding_count": 1,
                "placeholder_embedding_count": 0,
                "indexed_chunk_ids": [],
                "skipped_chunk_ids": ["chunk-1"],
                "warnings": ["vector_store_not_configured"],
                "metadata": {"local_only": True},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-placement-proposals.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/review.pdf",
                "relative_path": "Review/review.pdf",
                "sample_path": str(second_run_dir / "review.pdf"),
                "primary_tag": "scrapbooks",
                "proposal": {
                    "placement_status": "needs_review",
                    "placement_rule": "by_year",
                    "destination_path": "90_Intake_Needs_Review/06_History_Archive",
                    "date_confidence": "missing",
                },
                "metadata": {"tag_confidence": 0.52, "candidate_count": 1},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (second_run_dir / "sample-import-results.jsonl").write_text(
        json.dumps(
            {
                "import_status": "skipped",
                "importer": "noop",
                "output_dir": str(second_run_dir),
                "reason": "run_results_importer_not_configured",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    client = TestClient(app)
    run = client.post(
        "/admin/runs",
        json={"preset_key": "qa_samples_fast", "input_root": str(tmp_path / "input"), "output_dir": str(output_dir), "start": False},
    )
    report = client.get(f"/admin/runs/{run.json()['id']}/report")

    assert report.status_code == 200
    payload = report.json()
    assert payload["progress"]["summary"]["processed_count"] == 2
    assert payload["status_buckets"]["accepted"] == 1
    assert payload["status_buckets"]["review_required"] == 1
    assert payload["review_queue"]["count"] == 1
    assert payload["ocr"]["document_count"] == 1
    assert payload["ocr"]["page_count"] == 1
    assert payload["source_identity"]["count"] == 1
    assert payload["source_identity"]["items"][0]["file_id"] == "file-review"
    assert payload["file_probes"]["count"] == 1
    assert payload["file_probes"]["by_media_type"]["pdf"] == 1
    assert payload["provider_selections"]["count"] == 1
    assert payload["provider_selections"]["by_selected_provider"]["current"] == 1
    assert payload["extraction"]["count"] == 1
    assert payload["provider_attempts"]["count"] == 1
    assert payload["provider_attempts"]["by_provider"]["current"] == 1
    assert payload["segments"]["count"] == 1
    assert payload["segments"]["requires_review_count"] == 1
    assert payload["segments"]["by_type"]["scrapbook_page_group"] == 1
    assert payload["indexing"]["by_status"]["skipped"] == 1
    assert payload["indexing"]["skipped_count"] == 1
    assert payload["indexing"]["semantic_embedding_count"] == 1
    assert payload["placement"]["proposal_count"] == 1
    assert payload["placement"]["proposal_status"]["needs_review"] == 1
    assert payload["imports"]["count"] == 1
    assert payload["imports"]["by_status"]["skipped"] == 1
    assert payload["model_usage"]["summary"]["total_calls"] == 1
    assert payload["model_usage"]["summary"]["external_calls"] == 1
    assert payload["distributions"]["primary_tag"]["meeting_records"] == 1
    assert payload["distributions"]["primary_tag"]["scrapbooks"] == 1


def test_delete_run_removes_run_owned_dashboard_rows_and_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_REVIEW_DB_PATH", str(tmp_path / "review.sqlite"))
    output_dir = tmp_path / "dashboard-runs" / "delete-me"
    output_dir.mkdir(parents=True)
    sample_file = tmp_path / "scan.pdf"
    sample_file.write_bytes(b"not a real source corpus file")
    result = {
        "sample_path": str(sample_file),
        "source_path": "/source/delete-me.pdf",
        "relative_path": "Review/delete-me.pdf",
        "route_status": "review_ocr_quality",
        "review_reason": "ocr_quality_not_trusted",
        "final_class": "scanned_document",
        "extraction_strategy": "ocr_page_level",
        "extraction_status": "extracted",
        "quality": "poor",
        "top_tag_candidate": "meeting_records",
        "secondary_tags": ["meeting_minutes"],
        "tag_confidence": 0.42,
        "llm_status": "skipped",
        "warnings": ["ocr_fallback_used:openai:gpt-4.1-mini"],
    }
    (output_dir / "sample-pipeline-results.jsonl").write_text(json.dumps(result) + "\n", encoding="utf-8")
    (output_dir / "sample-review-queue.jsonl").write_text(json.dumps(result) + "\n", encoding="utf-8")
    (output_dir / "sample-extraction-results.jsonl").write_text(json.dumps({**result, "text": "bad OCR text"}) + "\n", encoding="utf-8")
    (output_dir / "sample-model-usage.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/delete-me.pdf",
                "relative_path": "Review/delete-me.pdf",
                "purpose": "ocr_fallback",
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "status": "ok",
                "cost_basis": "external",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "sample-provider-attempts.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/delete-me.pdf",
                "relative_path": "Review/delete-me.pdf",
                "provider": "current",
                "capability": "extraction",
                "status": "extracted",
                "strategy": "ocr_page_level",
                "seconds": 0.2,
                "warnings": [],
                "metadata": {"local_only": True},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "sample-document-segments.jsonl").write_text(
        json.dumps(
            {
                "source_path": "/source/delete-me.pdf",
                "relative_path": "Review/delete-me.pdf",
                "segment_id": "delete:segment-001",
                "page_start": 1,
                "page_end": 4,
                "segment_index": 1,
                "segment_type": "single_document",
                "segment_confidence": 0.8,
                "requires_segment_review": False,
                "segment_boundary_evidence": ["default:single_document"],
                "metadata": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    client = TestClient(app)

    run = client.post(
        "/admin/runs",
        json={"preset_key": "qa_samples_fast", "input_root": str(tmp_path / "input"), "output_dir": str(output_dir), "start": False},
    )
    run_id = run.json()["id"]
    imported = client.post(f"/admin/runs/{run_id}/import-results", json={})
    items_before = client.get("/admin/review/items", params={"status": "all", "run_id": run_id})
    files_before = client.get("/admin/files/search", params={"run_id": run_id})
    usage_before = client.get(f"/admin/runs/{run_id}/model-usage")

    deleted = client.delete(f"/admin/runs/{run_id}")
    run_after = client.get(f"/admin/runs/{run_id}")
    items_after = client.get("/admin/review/items", params={"status": "all", "run_id": run_id})
    files_after = client.get("/admin/files/search", params={"run_id": run_id})

    assert imported.status_code == 200
    assert imported.json()["imported_review_items"] == 1
    assert imported.json()["imported_model_usage"] == 1
    assert imported.json()["imported_provider_attempts"] == 1
    assert imported.json()["imported_document_segments"] == 1
    assert len(items_before.json()) == 1
    assert files_before.json()["items"][0]["source_path"] == "/source/delete-me.pdf"
    assert usage_before.json()["summary"]["total_calls"] == 1
    assert deleted.status_code == 200
    assert deleted.json()["deleted_counts"]["review_items"] == 1
    assert deleted.json()["deleted_counts"]["file_index"] == 1
    assert deleted.json()["deleted_counts"]["pipeline_results"] == 1
    assert deleted.json()["deleted_counts"]["model_usage"] == 1
    assert deleted.json()["deleted_counts"]["provider_attempts"] == 1
    assert deleted.json()["deleted_counts"]["document_segments"] == 1
    assert deleted.json()["deleted_counts"]["pipeline_runs"] == 1
    assert deleted.json()["artifacts"]["deleted"] is True
    assert run_after.status_code == 404
    assert items_after.json() == []
    assert files_after.json()["items"] == []
    assert not output_dir.exists()


def test_api_pipeline_run_file_missing_file_returns_review_result(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_EMBEDDING_PROVIDER", "placeholder")
    output_dir = tmp_path / "api-out"

    response = TestClient(app).post(
        "/admin/pipeline/run-file",
        json={
            "input_file": str(tmp_path / "missing.pdf"),
            "output_dir": str(output_dir),
            "retry_attempts": 1,
            "enable_llm_tags": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["final_result"]["route_status"] == "review_failed_extraction"
    assert payload["final_result"]["review_reason"] == "file_missing"
    assert "file_missing" in payload["final_result"]["warnings"]


def test_api_review_import_list_and_decision(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_REVIEW_DB_PATH", str(tmp_path / "review.sqlite"))
    monkeypatch.setenv("SUNSHINE_EMBEDDING_PROVIDER", "placeholder")
    monkeypatch.setenv("SUNSHINE_OCR_FALLBACK_PROVIDER", "disabled")
    output_dir = tmp_path / "langgraph-out"
    output_dir.mkdir()
    sample_file = tmp_path / "review.pdf"
    sample_file.write_bytes(b"review pdf bytes")
    result = {
        "sample_path": str(sample_file),
        "source_path": "/source/review.pdf",
        "relative_path": "Sunshine shared folders/review.pdf",
        "route_status": "review_low_confidence_tag",
        "review_reason": "tag_confidence_below_threshold",
        "final_class": "document",
        "extraction_strategy": "text_extraction",
        "extraction_status": "extracted",
        "quality": "ok",
        "top_tag_candidate": "meeting_records",
        "secondary_tags": ["meeting_minutes", "financial_report"],
        "tag_confidence": 0.52,
        "llm_status": "skipped",
        "placement_status": "missing_date",
        "placement_date_confidence": "missing",
        "default_privacy": "club_internal",
        "destination_path": "01_Governance_Admin/needs-date",
        "warnings": [
            "ocr_fallback_note:mostly clear",
            "ocr_fallback_used:openai:gpt-4.1-mini",
            "ocr_original_snippet:xqz",
            "ocr_fallback_snippet:Extracted meeting minutes OCR snippet for review.",
        ],
    }
    (output_dir / "sample-pipeline-results.jsonl").write_text(json.dumps(result) + "\n", encoding="utf-8")
    (output_dir / "sample-review-queue.jsonl").write_text(json.dumps(result) + "\n", encoding="utf-8")
    (output_dir / "sample-extraction-results.jsonl").write_text(
        json.dumps({**result, "text": "Extracted meeting minutes OCR snippet for review."}) + "\n",
        encoding="utf-8",
    )
    client = TestClient(app)

    imported = client.post("/admin/review/import-langgraph-output", json={"output_dir": str(output_dir), "sample_routed_per_bucket": 0})
    summary = client.get("/admin/review/summary")
    placement_report = client.get("/admin/review/placement-report")
    review_export = client.get("/admin/review/export", params={"status": "all", "limit": 10})
    items = client.get("/admin/review/items")
    filtered_items = client.get(
        "/admin/review/items",
        params={"warning_type": "ocr_fallback_used", "source_collection": "sunshine_shared_folders"},
    )
    fallback_used_items = client.get("/admin/review/items", params={"status": "all", "ocr_fallback_used": "used"})
    fallback_not_used_items = client.get("/admin/review/items", params={"status": "all", "ocr_fallback_used": "not_used"})
    low_confidence_items = client.get("/admin/review/items", params={"status": "all", "confidence_bucket": "low"})
    item_id = items.json()[0]["id"]
    item_detail = client.get(f"/admin/review/items/{item_id}")
    ocr_poor = client.post(
        f"/admin/review/items/{item_id}/ocr-quality",
        json={"ocr_quality_label": "poor", "review_stage": "needs_ocr_review", "notes": "OCR is unreadable."},
    )
    review_facets = client.get("/admin/review/facets", params={"status": "all"})
    assigned_item = client.post(
        f"/admin/review/items/{item_id}/assign",
        json={"assigned_reviewer": "reviewer-a", "review_stage": "needs_tag_review", "priority": "high"},
    )
    decision = client.post(
        f"/admin/review/items/{item_id}/decision",
        json={
            "decision": "change",
            "correct_class": "document",
            "correct_tag": "annual_spring_tea",
            "correct_secondary_tags": ["event_material"],
            "correct_destination_path": "05_Events/2025",
            "correct_placement_year": "2025",
            "correct_privacy": "club_internal",
            "review_stage": "resolved",
            "reviewer": "james",
            "notes": "Path says tea.",
        },
    )
    golden_labels = client.get("/admin/review/golden-labels")
    golden_export_csv = client.get("/admin/review/golden-labels/export")
    golden_export_jsonl = client.get("/admin/review/golden-labels/export", params={"format": "jsonl"})
    label_id = golden_labels.json()[0]["id"]
    golden_file = client.get(f"/admin/review/golden-labels/{label_id}/file")
    edited_label = client.patch(
        f"/admin/review/golden-labels/{label_id}",
        json={
            "content_class": "document",
            "correct_primary_tag": "meeting_records",
            "correct_secondary_tags": ["meeting_minutes"],
            "ocr_quality_label": "ok",
            "expected_review_required": False,
            "sensitive_record": True,
            "correct_destination_path": "01_Governance_Admin/2025",
            "correct_placement_year": "2025",
            "correct_privacy": "restricted",
            "reviewer": "auditor",
            "notes": "Corrected from dashboard.",
        },
    )
    golden_summary = client.get("/admin/review/golden-labels/summary")
    semantic_status_before = client.get("/admin/semantic-index/status", params={"index_db": str(tmp_path / "semantic.sqlite")})
    semantic_build = client.post(
        "/admin/semantic-index/build",
        json={"output_db": str(tmp_path / "semantic.sqlite")},
    )
    eval_output_dir = tmp_path / "semantic-eval"
    semantic_eval = client.post("/admin/semantic-eval/run", json={"output_dir": str(eval_output_dir)})
    semantic_eval_latest = client.get("/admin/semantic-eval/latest", params={"output_dir": str(eval_output_dir)})
    pipeline_eval_output_dir = tmp_path / "pipeline-eval"
    pipeline_eval = client.post(
        "/admin/pipeline-eval/run",
        json={"output_dir": str(pipeline_eval_output_dir), "disable_semantic_index": True, "embedding_provider": "placeholder"},
    )
    pipeline_eval_latest = client.get("/admin/pipeline-eval/latest", params={"output_dir": str(pipeline_eval_output_dir)})
    pipeline_eval_import = client.post("/admin/pipeline-eval/import", json={"output_dir": str(pipeline_eval_output_dir)})
    pipeline_eval_runs = client.get("/admin/pipeline-eval/runs")
    pipeline_eval_run_id = pipeline_eval.json()["eval_run"]["id"]
    pipeline_eval_results = client.get(f"/admin/pipeline-eval/runs/{pipeline_eval_run_id}/results")
    pipeline_eval_failures = client.get(f"/admin/pipeline-eval/runs/{pipeline_eval_run_id}/results", params={"result_type": "failures"})
    pipeline_eval_failure_groups = client.get(f"/admin/pipeline-eval/runs/{pipeline_eval_run_id}/results", params={"result_type": "failure_groups"})
    pipeline_eval_model_usage = client.get(f"/admin/pipeline-eval/runs/{pipeline_eval_run_id}/results", params={"result_type": "model_usage"})
    pipeline_eval_artifact_manifest = client.get(f"/admin/pipeline-eval/runs/{pipeline_eval_run_id}/results", params={"result_type": "artifact_manifest"})
    pipeline_eval_output_dir_2 = tmp_path / "pipeline-eval-2"
    pipeline_eval_2 = client.post(
        "/admin/pipeline-eval/run",
        json={"output_dir": str(pipeline_eval_output_dir_2), "disable_semantic_index": True},
    )
    pipeline_eval_comparison = client.get(
        f"/admin/pipeline-eval/runs/{pipeline_eval_2.json()['eval_run']['id']}/compare",
        params={"baseline_eval_run_id": pipeline_eval_run_id},
    )
    deleted_label = client.delete(f"/admin/review/golden-labels/{label_id}")
    file_response = client.get(f"/admin/review/items/{item_id}/file")
    files = client.get("/admin/files", params={"q": "meeting minutes"})
    file_id = files.json()[0]["id"]
    file_text = client.get(f"/admin/files/{file_id}/text")
    file_review = client.post(f"/admin/files/{file_id}/review", json={"review_reason": "manual_file_review"})
    file_run = client.post(
        f"/admin/files/{file_id}/run",
        json={
            "output_dir": str(tmp_path / "single-file-run"),
            "start": False,
            "embedding_provider": "cortex",
            "enable_llm_tags": True,
            "llm_tag_provider": "cortex",
            "ocr_fallback_provider": "cortex",
        },
    )
    presets = client.get("/admin/runs/presets")
    run = client.post(
        "/admin/runs",
        json={
            "preset_key": "qa_samples_fast",
            "run_role": "evaluation",
            "input_root": str(tmp_path / "input"),
            "output_dir": str(tmp_path / "run-output"),
            "embedding_provider": "cortex",
            "enable_llm_tags": True,
            "llm_tag_provider": "cortex",
            "ocr_fallback_provider": "cortex",
            "start": False,
        },
    )
    assert run.json()["run_role"] == "evaluation"
    assert run.json()["run_metadata"]["run_role"] == "evaluation"
    failed_empty_run = client.post(
        "/admin/runs",
        json={
            "preset_key": "qa_samples_fast",
            "input_root": str(tmp_path / "empty-input"),
            "output_dir": str(tmp_path / "empty-run-output"),
            "start": True,
        },
    )
    run_results = client.get(f"/admin/runs/{run.json()['id']}/results")
    cancelled_run = client.post(f"/admin/runs/{run.json()['id']}/cancel", json={})
    previous_output = tmp_path / "previous-run-output"
    current_output = tmp_path / "current-run-output"
    previous_output.mkdir()
    current_output.mkdir()
    previous_result = {**result, "top_tag_candidate": "meeting_records", "route_status": "review_low_confidence_tag"}
    current_result = {**result, "top_tag_candidate": "annual_spring_tea", "route_status": "route_candidate"}
    (previous_output / "sample-pipeline-results.jsonl").write_text(json.dumps(previous_result) + "\n", encoding="utf-8")
    (current_output / "sample-pipeline-results.jsonl").write_text(json.dumps(current_result) + "\n", encoding="utf-8")
    (current_output / "sample-model-usage.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "purpose": "tag_inspection",
                        "provider": "cortex",
                        "model": "gemma4-26b",
                        "status": "ok",
                        "runtime_ms": 1200,
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "total_tokens": 120,
                        "cost_basis": "local",
                    }
                ),
                json.dumps(
                    {
                        "purpose": "ocr_fallback",
                        "provider": "openai",
                        "model": "gpt-4.1-mini",
                        "status": "failed",
                        "runtime_ms": 800,
                        "input_tokens": 200,
                        "output_tokens": 50,
                        "total_tokens": 250,
                        "estimated_cost_usd": 0.0123,
                        "cost_basis": "external",
                        "error": "timeout",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    previous_run = client.post(
        "/admin/runs",
        json={"preset_key": "qa_samples_fast", "input_root": str(tmp_path / "input"), "output_dir": str(previous_output), "start": False},
    )
    current_run = client.post(
        "/admin/runs",
        json={"preset_key": "qa_samples_fast", "input_root": str(tmp_path / "input"), "output_dir": str(current_output), "embedding_provider": "cortex", "start": False},
    )
    imported_run_results = client.post(f"/admin/runs/{current_run.json()['id']}/import-results", json={})
    run_comparison = client.get(f"/admin/runs/{current_run.json()['id']}/compare-previous")
    run_artifacts = client.get(f"/admin/runs/{current_run.json()['id']}/artifacts")
    run_model_usage = client.get(f"/admin/runs/{current_run.json()['id']}/model-usage")
    run_report = client.get(f"/admin/runs/{current_run.json()['id']}/report")
    file_search = client.get("/admin/files/search", params={"q": "meeting minutes", "limit": 10})
    file_search_by_tag = client.get("/admin/files/search", params={"primary_tag": "annual_spring_tea", "limit": 10})
    file_search_by_review = client.get("/admin/files/search", params={"review_status": "open", "limit": 10})
    file_facets = client.get("/admin/files/facets", params={"q": "meeting"})
    file_inspection = client.get(f"/admin/files/{file_id}/inspection")
    runs = client.get("/admin/runs")
    run_events = client.get(f"/admin/runs/{run.json()['id']}/events")
    run_progress = client.get(f"/admin/runs/{run.json()['id']}/progress")

    assert imported.status_code == 200
    assert imported.json()["imported_review_items"] == 1
    assert summary.json()["total_review_items"] == 1
    assert summary.json()["results_by_secondary_tag"]["financial_report"] == 1
    assert placement_report.status_code == 200
    assert placement_report.json()["by_placement_status"]["missing_date"] == 1
    assert placement_report.json()["by_privacy"]["club_internal"] == 1
    assert placement_report.json()["missing_date_queue"]
    assert review_export.status_code == 200
    assert "relative_path,source_path" in review_export.text
    assert "Sunshine shared folders/review.pdf" in review_export.text
    assert items.json()[0]["review_reason"] == "tag_confidence_below_threshold"
    assert items.json()[0]["secondary_tags"] == ["meeting_minutes", "financial_report"]
    assert items.json()[0]["extraction_text_snippet"] == "Extracted meeting minutes OCR snippet for review."
    assert items.json()[0]["display_warnings"] == ["ocr_fallback_used:openai:gpt-4.1-mini"]
    assert items.json()[0]["ocr_evidence"]["fallback_used"] is True
    assert items.json()[0]["ocr_evidence"]["original_text_snippet"] == "xqz"
    assert items.json()[0]["ocr_evidence"]["fallback_text_snippet"] == "Extracted meeting minutes OCR snippet for review."
    assert filtered_items.status_code == 200
    assert len(filtered_items.json()) == 1
    assert fallback_used_items.status_code == 200
    assert len(fallback_used_items.json()) == 1
    assert fallback_not_used_items.status_code == 200
    assert fallback_not_used_items.json() == []
    assert low_confidence_items.status_code == 200
    assert low_confidence_items.json()[0]["confidence"] == 0.52
    assert item_detail.status_code == 200
    assert item_detail.json()["id"] == item_id
    assert ocr_poor.status_code == 200
    assert ocr_poor.json()["ocr_quality_label"] == "poor"
    assert ocr_poor.json()["review_stage"] == "needs_ocr_review"
    assert "OCR is unreadable." in ocr_poor.json()["notes"]
    assert review_facets.status_code == 200
    assert review_facets.json()["review_reason"]["tag_confidence_below_threshold"] == 1
    assert review_facets.json()["confidence_bucket"]["low"] == 1
    assert review_facets.json()["ocr_fallback_used"]["used"] == 1
    assert review_facets.json()["primary_tag"]["meeting_records"] == 1
    assert assigned_item.status_code == 200
    assert assigned_item.json()["assigned_reviewer"] == "reviewer-a"
    assert assigned_item.json()["priority"] == "high"
    assert decision.json()["status"] == "resolved"
    assert decision.json()["correct_tag"] == "annual_spring_tea"
    assert decision.json()["correct_secondary_tags"] == ["event_material"]
    assert decision.json()["correct_destination_path"] == "05_Events/2025"
    assert decision.json()["correct_placement_year"] == "2025"
    assert decision.json()["correct_privacy"] == "club_internal"
    assert decision.json()["review_stage"] == "resolved"
    assert golden_labels.status_code == 200
    assert golden_labels.json()[0]["correct_primary_tag"] == "annual_spring_tea"
    assert golden_labels.json()[0]["correct_secondary_tags"] == ["event_material"]
    assert golden_labels.json()[0]["ocr_quality_label"] == "poor"
    assert golden_labels.json()[0]["reviewed_at"]
    assert golden_export_csv.status_code == 200
    assert "correct_primary_tag" in golden_export_csv.text
    assert "reviewed_at" in golden_export_csv.text
    assert "annual_spring_tea" in golden_export_csv.text
    assert golden_export_jsonl.status_code == 200
    assert json.loads(golden_export_jsonl.text.splitlines()[0])["correct_primary_tag"] == "annual_spring_tea"
    assert golden_file.status_code == 200
    assert golden_file.content == b"review pdf bytes"
    assert edited_label.status_code == 200
    assert edited_label.json()["content_class"] == "document"
    assert edited_label.json()["correct_primary_tag"] == "meeting_records"
    assert edited_label.json()["correct_secondary_tags"] == ["meeting_minutes"]
    assert edited_label.json()["ocr_quality_label"] == "ok"
    assert edited_label.json()["expected_review_required"] is False
    assert edited_label.json()["sensitive_record"] is True
    assert edited_label.json()["correct_destination_path"] == "01_Governance_Admin/2025"
    assert edited_label.json()["correct_placement_year"] == "2025"
    assert edited_label.json()["correct_privacy"] == "restricted"
    assert golden_summary.json()["total_golden_labels"] == 1
    assert semantic_status_before.status_code == 200
    assert semantic_status_before.json()["exists"] is False
    assert semantic_build.status_code == 200
    assert semantic_build.json()["indexed"] == 1
    assert semantic_build.json()["status"]["indexed"] == 1
    assert semantic_eval.status_code == 200
    assert semantic_eval.json()["report"]["total_golden_labels"] == 1
    assert semantic_eval_latest.status_code == 200
    assert semantic_eval_latest.json()["exists"] is True
    assert pipeline_eval.status_code == 200
    assert pipeline_eval.json()["report"]["total_golden_labels"] == 1
    assert pipeline_eval.json()["report"]["evaluated_predictions"] == 1
    assert pipeline_eval.json()["report"]["run_metadata"]["taxonomy_version"].endswith(".json")
    assert pipeline_eval.json()["report"]["run_metadata"]["embedding_provider"] == "placeholder"
    assert pipeline_eval.json()["report"]["run_metadata"]["extraction_provider"] == "current"
    assert pipeline_eval.json()["report"]["run_metadata"]["ocr_fallback_mode"] == "disabled"
    assert "git_commit" in pipeline_eval.json()["eval_run"]["run_metadata"]
    assert pipeline_eval.json()["eval_run"]["evaluated_predictions"] == 1
    assert (pipeline_eval_output_dir / "eval-summary.json").exists()
    assert pipeline_eval_latest.status_code == 200
    assert pipeline_eval_latest.json()["exists"] is True
    assert pipeline_eval_import.status_code == 200
    assert pipeline_eval_import.json()["eval_run"]["output_dir"] == str(pipeline_eval_output_dir)
    assert pipeline_eval_import.json()["report"]["artifacts"]["summary"] == str(pipeline_eval_output_dir / "eval-summary.json")
    assert pipeline_eval_runs.status_code == 200
    assert pipeline_eval_runs.json()[0]["output_dir"] == str(pipeline_eval_output_dir)
    assert pipeline_eval_results.status_code == 200
    assert pipeline_eval_results.json()["result_type"] == "results"
    assert pipeline_eval_results.json()["count"] == 1
    assert pipeline_eval_failures.status_code == 200
    assert pipeline_eval_failures.json()["result_type"] == "failures"
    assert pipeline_eval_failure_groups.status_code == 200
    assert pipeline_eval_failure_groups.json()["result_type"] == "failure_groups"
    assert pipeline_eval_model_usage.status_code == 200
    assert pipeline_eval_model_usage.json()["result_type"] == "model_usage"
    assert pipeline_eval_artifact_manifest.status_code == 200
    assert pipeline_eval_artifact_manifest.json()["result_type"] == "artifact_manifest"
    assert any(item["name"] == "summary" and len(item["sha256"]) == 64 for item in pipeline_eval_artifact_manifest.json()["items"])
    assert pipeline_eval_2.status_code == 200
    assert pipeline_eval_comparison.status_code == 200
    assert pipeline_eval_comparison.json()["shared_file_count"] == 1
    assert "primary_accuracy" in pipeline_eval_comparison.json()["metric_deltas"]
    assert pipeline_eval_comparison.json()["changed_prediction_count"] == 0
    assert pipeline_eval_comparison.json()["changed_secondary_tag_count"] == 0
    assert pipeline_eval_comparison.json()["changed_secondary_tags"] == []
    assert deleted_label.status_code == 200
    assert deleted_label.json()["deleted"] is True
    assert file_response.status_code == 200
    assert file_response.content == b"review pdf bytes"
    assert files.status_code == 200
    assert files.json()[0]["latest_result"]["top_tag_candidate"] == "meeting_records"
    assert files.json()[0]["latest_result"]["ocr_evidence"]["fallback_provider"] == "openai:gpt-4.1-mini"
    assert file_text.json()["text"] == "Extracted meeting minutes OCR snippet for review."
    assert file_review.status_code == 200
    assert file_review.json()["review_reason"] == "manual_file_review"
    assert file_run.status_code == 200
    assert file_run.json()["preset_key"] == "single_file_debug"
    assert file_run.json()["embedding_provider"] == "cortex"
    assert file_run.json()["llm_tag_provider"] == "cortex"
    assert file_run.json()["ocr_fallback_provider"] == "cortex"
    assert "--input-file" in file_run.json()["command"]
    assert "--embedding-provider" in file_run.json()["command"]
    assert presets.status_code == 200
    assert any(preset["preset_key"] == "qa_samples_fast" for preset in presets.json())
    assert any(preset["preset_key"] == "single_file_debug" for preset in presets.json())
    assert run.status_code == 200
    assert run.json()["status"] == "queued"
    assert run.json()["embedding_provider"] == "cortex"
    assert run.json()["llm_tag_provider"] == "cortex"
    assert run.json()["ocr_fallback_provider"] == "cortex"
    assert "--embedding-provider" in run.json()["command"]
    assert failed_empty_run.status_code == 200
    assert failed_empty_run.json()["status"] == "failed"
    assert "No runnable QA sample indexes" in failed_empty_run.json()["error"]
    assert run_results.status_code == 200
    assert run_results.json()["result_type"] == "none"
    assert cancelled_run.status_code == 200
    assert cancelled_run.json()["status"] == "cancelled"
    assert previous_run.status_code == 200
    assert current_run.status_code == 200
    assert current_run.json()["embedding_provider"] == "cortex"
    assert current_run.json()["run_metadata"]["embedding_provider"] == "cortex"
    assert current_run.json()["run_metadata"]["taxonomy_version"].endswith(".json")
    assert imported_run_results.status_code == 200
    assert imported_run_results.json()["imported_model_usage"] == 2
    assert run_comparison.status_code == 200
    assert run_comparison.json()["previous_run_id"] == previous_run.json()["id"]
    assert run_comparison.json()["summary"]["changed"] == 1
    assert "top_tag_candidate" in run_comparison.json()["changed"][0]["changed_fields"]
    assert run_artifacts.status_code == 200
    assert any(artifact["name"] == "sample-pipeline-results.jsonl" and artifact["exists"] for artifact in run_artifacts.json()["artifacts"])
    assert any(artifact["name"] == "sample-structure.jsonl" for artifact in run_artifacts.json()["artifacts"])
    result_artifact = next(artifact for artifact in run_artifacts.json()["artifacts"] if artifact["name"] == "sample-pipeline-results.jsonl")
    assert len(result_artifact["sha256"]) == 64
    assert run_model_usage.status_code == 200
    assert run_model_usage.json()["summary"]["total_calls"] == 2
    assert run_model_usage.json()["summary"]["failed_calls"] == 1
    assert run_model_usage.json()["summary"]["local_calls"] == 1
    assert run_model_usage.json()["summary"]["external_calls"] == 1
    assert run_model_usage.json()["summary"]["unknown_cost_basis_calls"] == 0
    assert run_model_usage.json()["summary"]["cost_basis_completeness_rate"] == 1.0
    assert run_model_usage.json()["summary"]["total_tokens"] == 370
    assert run_model_usage.json()["summary"]["estimated_external_cost_usd"] == 0.0123
    assert run_report.status_code == 200
    assert run_report.json()["model_usage"]["summary"]["total_calls"] == 2
    assert run_report.json()["status_buckets"]["accepted"] == 1
    assert run_report.json()["status_buckets"]["review_required"] == 0
    assert run_report.json()["status_buckets"]["failed"] == 0
    assert run_report.json()["status_buckets"]["deferred"] == 0
    assert run_report.json()["overview"]["status_buckets"]["accepted"] == 1
    assert run_report.json()["distributions"]["primary_tag"]["annual_spring_tea"] == 1
    assert run_report.json()["review_queue"]["links"]["all"] == f"/review?run_id={current_run.json()['id']}&status=all"
    assert "tag_disagreements" in run_report.json()["review_queue"]["links"]
    assert "review_rate" in run_report.json()["training_cycle"]
    assert run_report.json()["artifacts"]
    assert file_search.status_code == 200
    assert file_search.json()["items"][0]["filename"] == "review.pdf"
    assert "latest_result" not in file_search.json()["items"][0]
    assert file_search.json()["items"][0]["text_snippet"] == "Extracted meeting minutes OCR snippet for review."
    assert "latest_run_key" in file_search.json()["items"][0]
    assert file_search_by_tag.status_code == 200
    assert file_search_by_tag.json()["items"][0]["primary_tag"] == "annual_spring_tea"
    assert file_search_by_review.status_code == 200
    assert file_search_by_review.json()["items"][0]["review_status"] == "open"
    assert file_facets.status_code == 200
    assert file_facets.json()["primary_tag"]["annual_spring_tea"] == 1
    assert file_facets.json()["review_status"]["open"] == 1
    assert file_inspection.status_code == 200
    assert file_inspection.json()["file"]["filename"] == "review.pdf"
    assert file_inspection.json()["latest_result"]["top_tag_candidate"] == "annual_spring_tea"
    assert file_inspection.json()["review_item"]["status"] == "open"
    assert file_inspection.json()["text"]["text"] == "Extracted meeting minutes OCR snippet for review."
    assert "preview_url" in file_inspection.json()["actions"]
    assert runs.json()[0]["preset_key"] == "qa_samples_fast"
    assert run_events.status_code == 200
    assert run_events.json()
    assert run_progress.status_code == 200
    assert run_progress.json()["run_id"] == run.json()["id"]
    assert "summary" in run_progress.json()
