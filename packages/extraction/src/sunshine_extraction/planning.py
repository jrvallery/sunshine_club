"""Build extraction plans from corrected content-class decisions."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO


VALID_FINAL_CLASSES = {
    "document",
    "scanned_document",
    "image",
    "spreadsheet",
    "shortcut",
    "archive",
    "image_edit_sidecar",
    "video",
    "database",
}
DEFER_REASONS_BY_CLASS = {
    "document": "publisher_conversion_required",
    "shortcut": "shortcut_resolution_required",
    "archive": "archive_unpack_required",
    "video": "video_metadata_required",
    "database": "database_export_required",
    "image_edit_sidecar": "sidecar_resolution_required",
}


def build_extraction_plan(
    corrected_path: str | Path,
    *,
    plan_path: str | Path,
    summary_path: str | Path,
) -> dict[str, Any]:
    corrected = Path(corrected_path)
    plan = Path(plan_path)
    summary = Path(summary_path)

    counters: Counter[str] = Counter()
    by_final_class: Counter[str] = Counter()
    by_final_status: Counter[str] = Counter()
    by_strategy: Counter[str] = Counter()
    by_subtype: Counter[str] = Counter()
    by_defer_reason: Counter[str] = Counter()
    by_search_enabled: Counter[str] = Counter()
    by_chat_enabled: Counter[str] = Counter()
    unplanned = 0

    plan.parent.mkdir(parents=True, exist_ok=True)
    with corrected.open("r", encoding="utf-8") as input_file, plan.open("w", encoding="utf-8") as output_file:
        for line in input_file:
            row = json.loads(line)
            plan_row = plan_corrected_row(row)
            _write_jsonl(output_file, plan_row)

            counters["total_rows"] += 1
            by_final_class[plan_row["final_class"]] += 1
            by_final_status[plan_row["final_status"]] += 1
            by_strategy[plan_row["strategy"]] += 1
            by_subtype[plan_row["document_subtype"] or "none"] += 1
            by_search_enabled[str(plan_row["search_enabled"]).lower()] += 1
            by_chat_enabled[str(plan_row["chat_enabled"]).lower()] += 1
            if plan_row["defer_reason"]:
                by_defer_reason[plan_row["defer_reason"]] += 1
            if plan_row["strategy"] == "unplanned":
                unplanned += 1

    summary_data = {
        "generated_at": datetime.now(UTC).isoformat(),
        "corrected_path": str(corrected),
        "plan_path": str(plan),
        "total_rows": counters["total_rows"],
        "unplanned_files": unplanned,
        "by_final_class": dict(sorted(by_final_class.items())),
        "by_final_status": dict(sorted(by_final_status.items())),
        "by_strategy": dict(sorted(by_strategy.items())),
        "by_document_subtype": dict(sorted(by_subtype.items())),
        "by_defer_reason": dict(sorted(by_defer_reason.items())),
        "by_search_enabled": dict(sorted(by_search_enabled.items())),
        "by_chat_enabled": dict(sorted(by_chat_enabled.items())),
    }
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(summary_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary_data


def plan_corrected_row(row: dict[str, Any]) -> dict[str, Any]:
    final_class = str(row.get("final_class") or "")
    final_status = str(row.get("final_status") or "")
    if final_class not in VALID_FINAL_CLASSES:
        raise ValueError(f"Unsupported final_class {final_class!r} for {row.get('relative_path')}")

    if final_status == "deferred_technical":
        return _deferred_plan(row)
    if final_status != "accepted":
        raise ValueError(f"Unsupported final_status {final_status!r} for {row.get('relative_path')}")

    if final_class == "scanned_document":
        return _scanned_document_plan(row)
    if final_class == "document":
        return _document_plan(row)
    if final_class == "image":
        return _image_plan(row)
    if final_class == "spreadsheet":
        return _spreadsheet_plan(row)

    raise ValueError(f"Accepted file has non-extractable final_class {final_class!r} for {row.get('relative_path')}")


def _base_plan(row: dict[str, Any], *, strategy: str, planning_reasons: list[str]) -> dict[str, Any]:
    return {
        "source_path": row["source_path"],
        "relative_path": row["relative_path"],
        "final_class": row["final_class"],
        "final_status": row["final_status"],
        "document_subtype": None,
        "strategy": strategy,
        "ocr_required": False,
        "ocr_fallback_if_empty": False,
        "page_level": False,
        "preserve_layout": False,
        "preserve_page_images": False,
        "extract_metadata": True,
        "extract_exif": False,
        "extract_dimensions": False,
        "use_path_context": False,
        "preserve_sheets": False,
        "preserve_rows": False,
        "preserve_columns": False,
        "detect_dates": False,
        "extract_now": True,
        "search_enabled": False,
        "chat_enabled": False,
        "quality_gate_required": True,
        "requires_followup": False,
        "defer_reason": None,
        "planning_reasons": planning_reasons,
    }


def _scanned_document_plan(row: dict[str, Any]) -> dict[str, Any]:
    subtype, subtype_reason = _document_subtype(row)
    plan = _base_plan(
        row,
        strategy="ocr_page_level",
        planning_reasons=["final_class=scanned_document", subtype_reason],
    )
    plan.update(
        {
            "document_subtype": subtype,
            "ocr_required": True,
            "page_level": True,
            "preserve_layout": True,
            "preserve_page_images": True,
            "search_enabled": True,
            "chat_enabled": True,
        }
    )
    return plan


def _document_plan(row: dict[str, Any]) -> dict[str, Any]:
    plan = _base_plan(row, strategy="text_extraction", planning_reasons=["final_class=document"])
    plan.update(
        {
            "ocr_fallback_if_empty": True,
            "page_level": _is_pdf(row),
            "preserve_layout": _is_pdf(row),
            "search_enabled": True,
            "chat_enabled": True,
        }
    )
    return plan


def _image_plan(row: dict[str, Any]) -> dict[str, Any]:
    plan = _base_plan(row, strategy="photo_metadata", planning_reasons=["final_class=image"])
    plan.update(
        {
            "extract_exif": True,
            "extract_dimensions": True,
            "use_path_context": True,
            "search_enabled": True,
            "chat_enabled": False,
            "planning_reasons": ["final_class=image", "metadata-only initial image extraction"],
        }
    )
    return plan


def _spreadsheet_plan(row: dict[str, Any]) -> dict[str, Any]:
    plan = _base_plan(row, strategy="spreadsheet_table_extraction", planning_reasons=["final_class=spreadsheet"])
    plan.update(
        {
            "preserve_sheets": True,
            "preserve_rows": True,
            "preserve_columns": True,
            "detect_dates": True,
            "search_enabled": True,
            "chat_enabled": True,
            "planning_reasons": ["final_class=spreadsheet", "preserve workbook table structure"],
        }
    )
    return plan


def _deferred_plan(row: dict[str, Any]) -> dict[str, Any]:
    final_class = str(row["final_class"])
    defer_reason = _defer_reason(row)
    plan = _base_plan(
        row,
        strategy="deferred_technical",
        planning_reasons=[f"final_status=deferred_technical", f"defer_reason={defer_reason}"],
    )
    plan.update(
        {
            "document_subtype": None,
            "extract_now": False,
            "extract_metadata": False,
            "search_enabled": False,
            "chat_enabled": False,
            "quality_gate_required": False,
            "requires_followup": True,
            "defer_reason": defer_reason,
        }
    )
    if final_class == "document":
        plan["planning_reasons"].append("publisher or malformed document conversion required")
    return plan


def _document_subtype(row: dict[str, Any]) -> tuple[str, str]:
    haystack = " ".join(
        str(row.get(key) or "")
        for key in ("relative_path", "review_notes", "transition_reason", "review_filename")
    ).lower()
    if "scrapbook" in haystack:
        return "scrapbook", "scrapbook evidence detected"
    if "newspaper" in haystack or "article" in haystack or "profile" in haystack:
        return "newspaper_article", "newspaper/article evidence detected"
    if any(token in haystack for token in ("receipt", "minutes", "guest", "mailing list", "insurance", "incorporation")):
        return "scanned_or_photographed_document", "generic scanned document evidence detected"
    return "unknown_scanned_document", "no scanned-document subtype evidence"


def _defer_reason(row: dict[str, Any]) -> str:
    final_class = str(row["final_class"])
    notes = str(row.get("review_notes") or "").lower()
    relative_path = str(row.get("relative_path") or "").lower()
    if "publisher" in notes or relative_path.endswith(".pub"):
        return "publisher_conversion_required"
    if final_class in DEFER_REASONS_BY_CLASS:
        return DEFER_REASONS_BY_CLASS[final_class]
    return "technical_handling_required"


def _is_pdf(row: dict[str, Any]) -> bool:
    return str(row.get("relative_path") or "").lower().endswith(".pdf")


def _write_jsonl(output: TextIO, row: dict[str, Any]) -> None:
    output.write(json.dumps(row, sort_keys=True))
    output.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build extraction plans from corrected content-class rows.")
    parser.add_argument("corrected", type=Path)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    build_extraction_plan(args.corrected, plan_path=args.plan, summary_path=args.summary)


if __name__ == "__main__":
    main()
