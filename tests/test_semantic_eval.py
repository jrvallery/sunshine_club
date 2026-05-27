from __future__ import annotations

import json
from pathlib import Path

from sunshine_api.review_store import ReviewStore
from sunshine_extraction.semantic_eval import evaluate_review_db


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_semantic_eval_reports_accuracy_and_mismatches(tmp_path: Path) -> None:
    output_dir = tmp_path / "langgraph-out"
    _write_jsonl(
        output_dir / "sample-pipeline-results.jsonl",
        [
            {
                "sample_path": str(tmp_path / "a.pdf"),
                "source_path": "/source/a.pdf",
                "relative_path": "Sunshine/a.pdf",
                "route_status": "review_low_confidence_tag",
                "review_reason": "tag_confidence_below_threshold",
                "final_class": "document",
                "extraction_strategy": "text_extraction",
                "extraction_status": "extracted",
                "quality": "ok",
                "top_tag_candidate": "meeting_records",
                "secondary_tags": ["membership"],
                "tag_confidence": 0.72,
                "llm_status": "skipped",
                "warnings": [],
            },
            {
                "sample_path": str(tmp_path / "b.pdf"),
                "source_path": "/source/b.pdf",
                "relative_path": "Sunshine/b.pdf",
                "route_status": "review_low_confidence_tag",
                "review_reason": "tag_confidence_below_threshold",
                "final_class": "document",
                "extraction_strategy": "text_extraction",
                "extraction_status": "extracted",
                "quality": "ok",
                "top_tag_candidate": "annual_spring_tea",
                "secondary_tags": [],
                "tag_confidence": 0.73,
                "llm_status": "skipped",
                "warnings": [],
            },
        ],
    )
    _write_jsonl(output_dir / "sample-review-queue.jsonl", [])
    _write_jsonl(output_dir / "sample-extraction-results.jsonl", [])
    store = ReviewStore(tmp_path / "review.sqlite")
    store.import_langgraph_output(output_dir, sample_routed_per_bucket=2)
    for item in store.list_review_items():
        correct_tag = "meeting_records" if item["source_path"] == "/source/a.pdf" else "history_archive_general"
        store.record_decision(item["id"], decision="change", correct_tag=correct_tag)

    report = evaluate_review_db(store.db_path, output=tmp_path / "eval.json", output_dir=tmp_path / "eval")

    assert report["total_golden_labels"] == 2
    assert report["correct_primary"] == 1
    assert report["incorrect_primary"] == 1
    assert report["primary_accuracy"] == 0.5
    assert report["secondary_precision"] == 0.0
    assert report["manual_review_required"] == 2
    assert report["mismatches"][0]["correct_primary_tag"] == "history_archive_general"
    assert (tmp_path / "eval.json").exists()
    assert (tmp_path / "eval" / "semantic-eval-summary.json").exists()
    assert (tmp_path / "eval" / "semantic-eval-results.jsonl").exists()
    assert (tmp_path / "eval" / "semantic-confusion-matrix.csv").exists()
    assert (tmp_path / "eval" / "semantic-review-required.csv").exists()
