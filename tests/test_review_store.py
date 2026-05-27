from __future__ import annotations

import json
from pathlib import Path

from sunshine_api.review_store import ReviewStore


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_review_store_imports_langgraph_results_and_records_decision(tmp_path: Path) -> None:
    output_dir = tmp_path / "langgraph-out"
    sample_file = tmp_path / "sample" / "b.pdf"
    sample_file.parent.mkdir()
    sample_file.write_bytes(b"pdf bytes")
    _write_jsonl(
        output_dir / "sample-pipeline-results.jsonl",
        [
            {
                "sample_path": "/sample/a.pdf",
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "route_status": "route_candidate",
                "review_reason": None,
                "final_class": "document",
                "extraction_strategy": "text_extraction",
                "extraction_status": "extracted",
                "quality": "ok",
                "top_tag_candidate": "annual_spring_tea",
                "secondary_tags": ["event_material", "guest_list"],
                "tag_confidence": 0.91,
                "llm_status": "inspected",
                "warnings": [],
            },
            {
                "sample_path": str(sample_file),
                "source_path": "/source/b.pdf",
                "relative_path": "Sunshine/b.pdf",
                "route_status": "review_ocr_quality",
                "review_reason": "ocr_quality_not_trusted",
                "final_class": "scanned_document",
                "extraction_strategy": "ocr_page_level",
                "extraction_status": "extracted",
                "quality": "poor",
                "top_tag_candidate": "meeting_records",
                "secondary_tags": ["meeting_minutes"],
                "tag_confidence": 0.72,
                "llm_status": "skipped",
                "warnings": ["ocr_confidence_below_threshold"],
            },
        ],
    )
    _write_jsonl(
        output_dir / "sample-review-queue.jsonl",
        [
            {
                "source_path": "/source/b.pdf",
                "relative_path": "Sunshine/b.pdf",
                "route_status": "review_ocr_quality",
                "review_reason": "ocr_quality_not_trusted",
            }
        ],
    )
    _write_jsonl(
        output_dir / "sample-extraction-results.jsonl",
        [
            {
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "text": "Annual Sunshine Tea guest list with names and event notes.",
            },
            {
                "source_path": "/source/b.pdf",
                "relative_path": "Sunshine/b.pdf",
                "text": "OCR text from scanned meeting minutes and treasurer notes.",
            },
        ],
    )
    _write_jsonl(
        output_dir / "sample-model-usage.jsonl",
        [
            {
                "source_path": "/source/b.pdf",
                "relative_path": "Sunshine/b.pdf",
                "purpose": "ocr_fallback",
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "status": "ok",
                "runtime_ms": 900,
                "total_tokens": 120,
                "estimated_cost_usd": 0.0042,
                "cost_basis": "external",
            },
            {
                "source_path": "/source/b.pdf",
                "relative_path": "Sunshine/b.pdf",
                "purpose": "tag_inspection",
                "provider": "cortex",
                "model": "gemma4-26b",
                "status": "ok",
                "runtime_ms": 300,
                "total_tokens": 80,
                "cost_basis": "local",
            },
        ],
    )
    store = ReviewStore(tmp_path / "review.sqlite")
    lineage_run = store.create_pipeline_run(
        preset_key="qa_samples_fast",
        run_role="evaluation",
        input_root="/tmp/input",
        output_dir=str(output_dir),
        command=["python", "-m", "sunshine_extraction.langgraph_pipeline"],
        embedding_provider="openai",
        enable_llm_tags=True,
        llm_tag_provider="cortex",
        ocr_fallback_provider="openai",
    )
    assert lineage_run["run_role"] == "evaluation"
    assert lineage_run["run_metadata"]["run_role"] == "evaluation"
    baseline_run = store.create_pipeline_run(
        preset_key="qa_samples_full",
        input_root="/tmp/qa samples",
        output_dir="/tmp/dashboard-runs/qa_samples_full",
        command=["python", "-m", "sunshine_extraction.langgraph_pipeline"],
        embedding_provider="cortex",
        enable_llm_tags=True,
        llm_tag_provider="cortex",
        ocr_fallback_provider="openai",
    )

    imported = store.import_langgraph_output(output_dir, sample_routed_per_bucket=1, sample_seed=7, run_id=lineage_run["id"])
    summary = store.summary()
    items = store.list_review_items()
    items_for_run = store.list_review_items(run_id=lineage_run["id"])
    facets = store.review_facets(status="all", run_id=lineage_run["id"])
    sampled_item = next(item for item in items if item["review_reason"] == "qa_random_route_candidate_sample")
    review_item = next(item for item in items if item["review_reason"] == "ocr_quality_not_trusted")
    updated = store.record_decision(
        review_item["id"],
        decision="accept",
        correct_class="scanned_document",
        correct_tag="meeting_records",
        correct_destination_path="01_Governance_Admin/1992-1993",
        correct_placement_year="1992-1993",
        correct_privacy="club_internal",
        ocr_quality_label="ok",
        expected_review_required=True,
        sensitive_record=True,
        review_stage="resolved",
        notes="Looks correct.",
        reviewer="james",
    )
    golden_labels = store.list_golden_labels()
    golden_summary = store.golden_label_summary()
    eval_record = store.record_pipeline_eval(
        {
            "labels_db": str(store.db_path),
            "output_dir": str(tmp_path / "eval-output"),
            "total_golden_labels": 1,
            "evaluated_predictions": 1,
            "primary_accuracy": 1.0,
            "content_class_accuracy": 1.0,
            "secondary_precision": 1.0,
            "secondary_recall": 1.0,
            "ocr_quality_accuracy": 1.0,
            "review_routing_accuracy": 1.0,
            "failure_count": 0,
            "model_usage": {"total_model_usage_rows": 3},
        }
    )
    eval_runs = store.list_pipeline_eval_runs()
    edited_label = store.update_golden_label(
        golden_labels[0]["id"],
        correct_primary_tag="governance_bylaws_policy",
        correct_secondary_tags=["policy"],
        content_class="document",
        ocr_quality_label="ok",
        expected_review_required=False,
        sensitive_record=False,
        reviewer="james",
        notes="Corrected after audit.",
    )
    deleted_label = store.delete_golden_label(edited_label["id"])

    assert imported["imported_results"] == 2
    assert imported["imported_review_items"] == 2
    assert imported["imported_sample_items"] == 1
    assert summary["total_results"] == 2
    assert summary["total_review_items"] == 2
    assert summary["review_by_status"]["open"] == 2
    assert summary["results_by_primary_tag"]["meeting_records"] == 1
    assert summary["results_by_secondary_tag"]["guest_list"] == 1
    assert summary["results_by_secondary_tag"]["meeting_minutes"] == 1
    assert sampled_item["route_status"] == "route_candidate"
    assert len(items_for_run) == 2
    assert facets["run"][str(lineage_run["id"])] == 2
    assert facets["preset"]["qa_samples_fast"] == 2
    assert facets["embedding_provider"]["openai"] == 2
    assert facets["llm_tags"]["enabled"] == 2
    assert facets["review_reason"]["ocr_quality_not_trusted"] == 1
    assert review_item["run_id"] == lineage_run["id"]
    assert review_item["run_key"] == lineage_run["run_key"]
    assert lineage_run["run_role"] == "evaluation"
    assert baseline_run["run_role"] == "baseline"
    assert baseline_run["run_metadata"]["run_role"] == "baseline"
    assert review_item["run_preset_key"] == "qa_samples_fast"
    assert review_item["embedding_provider"] == "openai"
    assert review_item["enable_llm_tags"] is True
    assert review_item["llm_tag_provider"] == "cortex"
    assert review_item["ocr_fallback_provider"] == "openai"
    assert review_item["model_usage_summary"]["scope"] == "file"
    assert review_item["model_usage_summary"]["total_calls"] == 2
    assert review_item["model_usage_summary"]["external_calls"] == 1
    assert review_item["model_usage_summary"]["local_calls"] == 1
    assert review_item["model_usage_summary"]["total_runtime_ms"] == 1200
    assert review_item["model_usage_summary"]["total_tokens"] == 200
    assert review_item["model_usage_summary"]["estimated_external_cost_usd"] == 0.0042
    assert review_item["model_usage_summary"]["purposes"] == ["ocr_fallback", "tag_inspection"]
    assert sampled_item["secondary_tags"] == ["event_material", "guest_list"]
    assert sampled_item["extraction_text_snippet"] == "Annual Sunshine Tea guest list with names and event notes."
    assert review_item["warnings"] == ["ocr_confidence_below_threshold"]
    assert review_item["display_warnings"] == ["ocr_confidence_below_threshold"]
    assert review_item["extraction_text_snippet"] == "OCR text from scanned meeting minutes and treasurer notes."
    assert updated["status"] == "resolved"
    assert updated["decision"] == "accept"
    assert updated["correct_secondary_tags"] == ["meeting_minutes"]
    assert updated["correct_destination_path"] == "01_Governance_Admin/1992-1993"
    assert updated["correct_placement_year"] == "1992-1993"
    assert updated["correct_privacy"] == "club_internal"
    assert updated["review_stage"] == "resolved"
    assert len(golden_labels) == 1
    assert golden_labels[0]["content_class"] == "scanned_document"
    assert golden_labels[0]["ocr_quality_label"] == "ok"
    assert golden_labels[0]["expected_review_required"] is True
    assert golden_labels[0]["sensitive_record"] is True
    assert golden_labels[0]["correct_destination_path"] == "01_Governance_Admin/1992-1993"
    assert golden_labels[0]["correct_placement_year"] == "1992-1993"
    assert golden_labels[0]["correct_privacy"] == "club_internal"
    assert edited_label["content_class"] == "document"
    assert edited_label["correct_primary_tag"] == "governance_bylaws_policy"
    assert edited_label["correct_secondary_tags"] == ["policy"]
    assert edited_label["expected_review_required"] is False
    assert edited_label["sensitive_record"] is False
    assert edited_label["reviewer"] == "james"
    assert edited_label["notes"] == "Corrected after audit."
    assert deleted_label["deleted"] is True
    assert store.list_golden_labels() == []
    assert golden_summary["total_golden_labels"] == 1
    assert golden_summary["golden_by_primary_tag"]["meeting_records"] == 1
    assert "meeting_records" in golden_summary["taxonomy_primary_tags"]
    assert "meeting_records" not in golden_summary["missing_primary_tags"]
    assert golden_summary["primary_coverage_rate"] is not None
    assert eval_record["evaluated_predictions"] == 1
    assert eval_record["primary_accuracy"] == 1.0
    assert eval_record["model_usage"]["total_model_usage_rows"] == 3
    assert eval_runs[0]["id"] == eval_record["id"]
    assert store.file_path_for_review_item(review_item["id"]) == sample_file

    files = store.list_files(q="meeting minutes")
    assert len(files) == 1
    assert files[0]["filename"] == "b.pdf"
    assert files[0]["latest_result"]["top_tag_candidate"] == "meeting_records"
    assert files[0]["latest_run_id"] == lineage_run["id"]
    assert files[0]["latest_run_key"] == lineage_run["run_key"]
    assert files[0]["latest_embedding_provider"] == "openai"
    assert store.file_path_for_file(files[0]["id"]) == sample_file
    assert store.file_text(files[0]["id"])["text"] == "OCR text from scanned meeting minutes and treasurer notes."
    manual_review = store.add_file_to_review(files[0]["id"], review_reason="manual_file_review")
    assert manual_review["status"] == "open"
    assert manual_review["review_reason"] == "manual_file_review"
    assert manual_review["run_id"] == lineage_run["id"]
    assigned = store.assign_review_item(manual_review["id"], assigned_reviewer="reviewer-a", review_stage="needs_ocr_review", priority="high")
    assert assigned["assigned_reviewer"] == "reviewer-a"
    assert assigned["review_stage"] == "needs_ocr_review"
    assert assigned["priority"] == "high"
    ignored = store.record_decision(manual_review["id"], decision="ignore", notes="Not useful.", save_as_golden=False)
    assert ignored["status"] == "resolved"

    run = store.create_pipeline_run(
        preset_key="qa_samples_fast",
        input_root="/tmp/input",
        output_dir="/tmp/output",
        command=["python", "-m", "sunshine_extraction.langgraph_pipeline"],
        embedding_provider="cortex",
        enable_llm_tags=False,
        llm_tag_provider="disabled",
        ocr_fallback_provider="disabled",
    )
    store.mark_pipeline_run_started(run["id"])
    store.mark_pipeline_run_finished(run["id"], status="succeeded", summary={"processed_count": 2, "by_route_status": {"route_candidate": 1}})
    runs = store.list_pipeline_runs()
    events = store.list_pipeline_run_events(run["id"])
    assert runs[0]["status"] == "succeeded"
    assert runs[0]["processed_count"] == 2
    assert events
