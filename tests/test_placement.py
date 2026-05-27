from __future__ import annotations

from sunshine_extraction.placement import resolve_tag_placement


def test_resolve_flat_tag_placement_from_taxonomy_seed() -> None:
    placement = resolve_tag_placement("anniversary_125th", relative_path="125th/project plan.docx")

    assert placement["placement_status"] == "resolved"
    assert placement["destination_path"] == "09_125th_Anniversary"
    assert placement["placement_rule"] == "flat"
    assert placement["default_privacy"] == "club_internal"
    assert "125th" in placement["definition"]


def test_resolve_by_year_tag_placement_uses_explicit_school_year_range() -> None:
    placement = resolve_tag_placement(
        "meeting_records",
        relative_path="Minutes Transcription/Years Completed to upload/1992-1993.pdf",
        text="SUNSHINE CLUB Year 1992-93 minutes and treasurer report.",
    )

    assert placement["placement_status"] == "resolved"
    assert placement["destination_path"] == "01_Governance_Admin/1992-1993"
    assert placement["placement_rule"] == "by_year"
    assert placement["date_confidence"] == "high"
    assert placement["date_evidence"] == ["path_year_range:1992-1993"]


def test_resolve_by_year_month_tag_requires_month() -> None:
    placement = resolve_tag_placement("system_exports_logs", relative_path="_manifest/sunshine-inventory-2026-05-25/report.json")

    assert placement["placement_status"] == "resolved"
    assert placement["destination_path"] == "99_System_Exports_Logs/2026/05"
    assert placement["placement_rule"] == "by_year_month"


def test_missing_date_goes_to_review_holding_area() -> None:
    placement = resolve_tag_placement("meeting_records", relative_path="Minutes/unknown.pdf", text="Meeting minutes without a date.")

    assert placement["placement_status"] == "needs_review"
    assert placement["destination_path"] == "90_Intake_Needs_Review/01_Governance_Admin"
    assert placement["review_reason"] == "missing_document_date"


def test_unknown_primary_tag_goes_to_review_holding_area() -> None:
    placement = resolve_tag_placement("not_a_real_tag", relative_path="x.pdf")

    assert placement["placement_status"] == "needs_review"
    assert placement["destination_path"] == "90_Intake_Needs_Review"
    assert placement["review_reason"] == "unknown_primary_tag"
