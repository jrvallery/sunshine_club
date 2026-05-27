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
    assert report["summary"]["unknown_external_cost_calls"] == 2
    assert report["by_purpose"]["ocr_fallback"]["calls"] == 1
    assert report["by_purpose"]["tag_inspection"]["calls"] == 1
    assert report["by_purpose"]["chunk_embedding"]["calls"] == 1


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
    assert len(items_before.json()) == 1
    assert files_before.json()["items"][0]["source_path"] == "/source/delete-me.pdf"
    assert usage_before.json()["summary"]["total_calls"] == 1
    assert deleted.status_code == 200
    assert deleted.json()["deleted_counts"]["review_items"] == 1
    assert deleted.json()["deleted_counts"]["file_index"] == 1
    assert deleted.json()["deleted_counts"]["pipeline_results"] == 1
    assert deleted.json()["deleted_counts"]["model_usage"] == 1
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
        "warnings": ["ocr_fallback_note:mostly clear", "ocr_fallback_used:openai:gpt-4.1-mini"],
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
    item_id = items.json()[0]["id"]
    item_detail = client.get(f"/admin/review/items/{item_id}")
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
    label_id = golden_labels.json()[0]["id"]
    golden_file = client.get(f"/admin/review/golden-labels/{label_id}/file")
    edited_label = client.patch(
        f"/admin/review/golden-labels/{label_id}",
        json={
            "correct_primary_tag": "meeting_records",
            "correct_secondary_tags": ["meeting_minutes"],
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
            "embedding_provider": "openai",
            "enable_llm_tags": True,
            "llm_tag_provider": "cortex",
            "ocr_fallback_provider": "openai",
        },
    )
    presets = client.get("/admin/runs/presets")
    run = client.post(
        "/admin/runs",
        json={
            "preset_key": "qa_samples_fast",
            "input_root": str(tmp_path / "input"),
            "output_dir": str(tmp_path / "run-output"),
            "embedding_provider": "openai",
            "enable_llm_tags": True,
            "llm_tag_provider": "cortex",
            "ocr_fallback_provider": "openai",
            "start": False,
        },
    )
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
        json={"preset_key": "qa_samples_fast", "input_root": str(tmp_path / "input"), "output_dir": str(current_output), "embedding_provider": "openai", "start": False},
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
    assert filtered_items.status_code == 200
    assert len(filtered_items.json()) == 1
    assert item_detail.status_code == 200
    assert item_detail.json()["id"] == item_id
    assert review_facets.status_code == 200
    assert review_facets.json()["review_reason"]["tag_confidence_below_threshold"] == 1
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
    assert golden_file.status_code == 200
    assert golden_file.content == b"review pdf bytes"
    assert edited_label.status_code == 200
    assert edited_label.json()["correct_primary_tag"] == "meeting_records"
    assert edited_label.json()["correct_secondary_tags"] == ["meeting_minutes"]
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
    assert deleted_label.status_code == 200
    assert deleted_label.json()["deleted"] is True
    assert file_response.status_code == 200
    assert file_response.content == b"review pdf bytes"
    assert files.status_code == 200
    assert files.json()[0]["latest_result"]["top_tag_candidate"] == "meeting_records"
    assert file_text.json()["text"] == "Extracted meeting minutes OCR snippet for review."
    assert file_review.status_code == 200
    assert file_review.json()["review_reason"] == "manual_file_review"
    assert file_run.status_code == 200
    assert file_run.json()["preset_key"] == "single_file_debug"
    assert file_run.json()["embedding_provider"] == "openai"
    assert file_run.json()["llm_tag_provider"] == "cortex"
    assert file_run.json()["ocr_fallback_provider"] == "openai"
    assert "--input-file" in file_run.json()["command"]
    assert "--embedding-provider" in file_run.json()["command"]
    assert presets.status_code == 200
    assert any(preset["preset_key"] == "qa_samples_fast" for preset in presets.json())
    assert any(preset["preset_key"] == "single_file_debug" for preset in presets.json())
    assert run.status_code == 200
    assert run.json()["status"] == "queued"
    assert run.json()["embedding_provider"] == "openai"
    assert run.json()["llm_tag_provider"] == "cortex"
    assert run.json()["ocr_fallback_provider"] == "openai"
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
    assert current_run.json()["embedding_provider"] == "openai"
    assert imported_run_results.status_code == 200
    assert imported_run_results.json()["imported_model_usage"] == 2
    assert run_comparison.status_code == 200
    assert run_comparison.json()["previous_run_id"] == previous_run.json()["id"]
    assert run_comparison.json()["summary"]["changed"] == 1
    assert "top_tag_candidate" in run_comparison.json()["changed"][0]["changed_fields"]
    assert run_artifacts.status_code == 200
    assert any(artifact["name"] == "sample-pipeline-results.jsonl" and artifact["exists"] for artifact in run_artifacts.json()["artifacts"])
    assert run_model_usage.status_code == 200
    assert run_model_usage.json()["summary"]["total_calls"] == 2
    assert run_model_usage.json()["summary"]["failed_calls"] == 1
    assert run_model_usage.json()["summary"]["total_tokens"] == 370
    assert run_model_usage.json()["summary"]["estimated_external_cost_usd"] == 0.0123
    assert run_report.status_code == 200
    assert run_report.json()["model_usage"]["summary"]["total_calls"] == 2
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
