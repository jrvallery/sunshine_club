from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from sunshine_extraction.corrections import apply_review_decisions


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _probe_row(source_path: str, relative_path: str, after_class: str, requires_review: bool) -> dict:
    return {
        "inventory_run_id": "inventory-test",
        "probe_run_id": "probe-test",
        "source_path": source_path,
        "relative_path": relative_path,
        "status": "probed",
        "before_class": "document",
        "after_class": after_class,
        "transition_reason": "test",
        "extractor_name": "test",
        "extractor_version": "v1",
        "extraction_quality": "poor",
        "confidence_after": 0.4,
        "requires_review": requires_review,
        "review_reasons": ["pdf_too_large_for_lightweight_probe"] if requires_review else [],
        "warnings": [],
        "metadata": {},
        "transition": {
            "source_path": source_path,
            "inventory_run_id": "inventory-test",
            "before_class": "document",
            "after_class": after_class,
            "transition_reason": "test",
            "extractor_name": "test",
            "extractor_version": "v1",
            "extraction_quality": "poor",
            "warnings": [],
            "requires_review": requires_review,
            "metadata": {},
        },
    }


def _write_review_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=["filename", "decision", "correct_class", "notes"])
        writer.writeheader()
        writer.writerows(rows)


def test_apply_review_decisions_writes_overrides_corrected_rows_and_summary(tmp_path: Path) -> None:
    probe_results = tmp_path / "probe-results.jsonl"
    review_index = tmp_path / "review-index.jsonl"
    review_decisions = tmp_path / "review-decisions.csv"
    overrides = tmp_path / "content-class-overrides.jsonl"
    corrected = tmp_path / "corrected-content-classes.jsonl"
    summary = tmp_path / "corrected-content-class-summary.json"

    _write_jsonl(
        probe_results,
        [
            _probe_row("/source/a.pdf", "a.pdf", "document", True),
            _probe_row("/source/b.jpg", "b.jpg", "image", False),
        ],
    )
    _write_jsonl(
        review_index,
        [
            {
                "link_name": "001 - a.pdf",
                "source_path": "/source/a.pdf",
                "relative_path": "a.pdf",
            }
        ],
    )
    _write_review_csv(
        review_decisions,
        [
            {
                "filename": "001 - a.pdf",
                "decision": "change_to_scanned_document",
                "correct_class": "scanned_document",
                "notes": "OCR page-by-page",
            }
        ],
    )

    summary_data = apply_review_decisions(
        probe_results,
        review_index,
        review_decisions,
        overrides_path=overrides,
        corrected_path=corrected,
        summary_path=summary,
    )

    override_rows = [json.loads(line) for line in overrides.read_text(encoding="utf-8").splitlines()]
    corrected_rows = [json.loads(line) for line in corrected.read_text(encoding="utf-8").splitlines()]

    assert summary_data["total_probe_results"] == 2
    assert summary_data["overrides"] == 1
    assert summary_data["by_final_class"]["scanned_document"] == 1
    assert summary_data["by_final_class"]["image"] == 1
    assert override_rows[0]["final_class"] == "scanned_document"
    assert corrected_rows[0]["requires_review"] is False
    assert corrected_rows[0]["review_decision"] == "change_to_scanned_document"
    assert corrected_rows[1]["review_decision"] is None


def test_apply_review_decisions_rejects_incomplete_rows(tmp_path: Path) -> None:
    probe_results = tmp_path / "probe-results.jsonl"
    review_index = tmp_path / "review-index.jsonl"
    review_decisions = tmp_path / "review-decisions.csv"

    _write_jsonl(probe_results, [_probe_row("/source/a.pdf", "a.pdf", "document", True)])
    _write_jsonl(review_index, [{"link_name": "001 - a.pdf", "source_path": "/source/a.pdf"}])
    _write_review_csv(review_decisions, [{"filename": "001 - a.pdf", "decision": "", "correct_class": "document", "notes": ""}])

    with pytest.raises(ValueError, match="incomplete"):
        apply_review_decisions(
            probe_results,
            review_index,
            review_decisions,
            overrides_path=tmp_path / "overrides.jsonl",
            corrected_path=tmp_path / "corrected.jsonl",
            summary_path=tmp_path / "summary.json",
        )
