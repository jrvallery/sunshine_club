from __future__ import annotations

import json
from pathlib import Path

import pytest

from sunshine_extraction.planning import build_extraction_plan, plan_corrected_row


def _row(final_class: str, final_status: str = "accepted", **overrides) -> dict:
    row = {
        "source_path": f"/source/{final_class}",
        "relative_path": f"Sunshine shared folders/{final_class}.pdf",
        "final_class": final_class,
        "final_status": final_status,
        "review_notes": None,
        "review_filename": None,
        "transition_reason": "test",
    }
    row.update(overrides)
    return row


def test_scanned_document_uses_page_ocr_and_preserves_layout() -> None:
    plan = plan_corrected_row(
        _row(
            "scanned_document",
            relative_path="Sunshine shared folders/Scrapbooks/2010-2014 Scrapbook.pdf",
            review_notes="Scrapbook PDF; OCR page-by-page and preserve page images/layout",
        )
    )

    assert plan["strategy"] == "ocr_page_level"
    assert plan["document_subtype"] == "scrapbook"
    assert plan["ocr_required"] is True
    assert plan["page_level"] is True
    assert plan["preserve_layout"] is True
    assert plan["preserve_page_images"] is True
    assert plan["search_enabled"] is True
    assert plan["chat_enabled"] is True


def test_newspaper_article_subtype_is_inferred_from_review_notes() -> None:
    plan = plan_corrected_row(
        _row(
            "scanned_document",
            relative_path="Sunshine shared folders/Articles and Features/Linda Snyder.pdf",
            review_notes="Newspaper/profile article; OCR and extract publication/date/source when available",
        )
    )

    assert plan["document_subtype"] == "newspaper_article"
    assert "newspaper/article evidence detected" in plan["planning_reasons"]


def test_document_uses_text_extraction_with_ocr_fallback() -> None:
    plan = plan_corrected_row(_row("document", relative_path="Sunshine shared folders/Admin Docs/policy.pdf"))

    assert plan["strategy"] == "text_extraction"
    assert plan["ocr_required"] is False
    assert plan["ocr_fallback_if_empty"] is True
    assert plan["search_enabled"] is True
    assert plan["chat_enabled"] is True


def test_image_uses_metadata_only_initial_strategy() -> None:
    plan = plan_corrected_row(_row("image", relative_path="Sunshine shared folders/Historical Photos/member.jpg"))

    assert plan["strategy"] == "photo_metadata"
    assert plan["extract_exif"] is True
    assert plan["extract_dimensions"] is True
    assert plan["use_path_context"] is True
    assert plan["search_enabled"] is True
    assert plan["chat_enabled"] is False


def test_spreadsheet_preserves_table_structure() -> None:
    plan = plan_corrected_row(_row("spreadsheet", relative_path="Sunshine shared folders/Treasurer/report.xlsm"))

    assert plan["strategy"] == "spreadsheet_table_extraction"
    assert plan["preserve_sheets"] is True
    assert plan["preserve_rows"] is True
    assert plan["preserve_columns"] is True
    assert plan["detect_dates"] is True


def test_deferred_technical_gets_specific_defer_reason() -> None:
    plan = plan_corrected_row(
        _row(
            "document",
            final_status="deferred_technical",
            relative_path="Sunshine shared folders/Teas/Logo Samples.pub",
            review_notes="Microsoft Publisher file; needs conversion",
        )
    )

    assert plan["strategy"] == "deferred_technical"
    assert plan["extract_now"] is False
    assert plan["search_enabled"] is False
    assert plan["chat_enabled"] is False
    assert plan["requires_followup"] is True
    assert plan["defer_reason"] == "publisher_conversion_required"
    assert plan["quality_gate_required"] is False


def test_build_extraction_plan_writes_one_plan_per_corrected_row(tmp_path: Path) -> None:
    corrected = tmp_path / "corrected-content-classes.jsonl"
    plan_path = tmp_path / "extraction-plan.jsonl"
    summary_path = tmp_path / "extraction-plan-summary.json"
    rows = [
        _row("scanned_document"),
        _row("document"),
        _row("image"),
        _row("spreadsheet"),
        _row("shortcut", final_status="deferred_technical"),
    ]
    corrected.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    summary = build_extraction_plan(corrected, plan_path=plan_path, summary_path=summary_path)

    plan_rows = [json.loads(line) for line in plan_path.read_text(encoding="utf-8").splitlines()]
    summary_data = json.loads(summary_path.read_text(encoding="utf-8"))

    assert len(plan_rows) == len(rows)
    assert summary["total_rows"] == len(rows)
    assert summary["unplanned_files"] == 0
    assert summary_data["by_strategy"]["ocr_page_level"] == 1
    assert summary_data["by_strategy"]["deferred_technical"] == 1


def test_invalid_final_class_fails_loudly() -> None:
    with pytest.raises(ValueError, match="Unsupported final_class"):
        plan_corrected_row(_row("unsupported"))
