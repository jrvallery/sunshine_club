"""Deterministic tag-rule service boundary."""

from __future__ import annotations

import json
from typing import Any

from sunshine_extraction.domain.tags import tag_candidate_row
from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import ExtractionResult


def assign_tag_candidates(sample: SampleFile, corrected: dict[str, Any], plan: dict[str, Any], extraction: ExtractionResult) -> list[dict[str, Any]]:
    if plan["strategy"] == "deferred_technical":
        return []

    haystack = " ".join(
        [
            sample.relative_path,
            sample.sample_path.name,
            str(plan.get("document_subtype") or ""),
            extraction.text[:4000],
            json.dumps(extraction.metadata, sort_keys=True),
            str(corrected.get("review_notes") or ""),
        ]
    ).lower()
    rules = [
        (
            "history_archive_general",
            0.93,
            ["founders of sunshine club", "organized in 1902", "purpose of the sunshine club", "membership has grown", "charitable projects"],
            "historical club summary evidence",
            ["history_archive", "programs_mission"],
        ),
        ("scrapbooks", 0.92, ["scrapbook"], "scrapbook evidence", []),
        ("press_publications", 0.9, ["newspaper", "article", "profile", "ledger", "clipping", "obituary"], "press/profile evidence", []),
        ("annual_spring_tea", 0.88, ["sunshine tea invitation", "tea guest list", "tea program", "/teas/", "teas/", "_tea", "guest list"], "tea/guest-list evidence", []),
        ("meeting_records", 0.87, ["meeting", "minutes", "agenda"], "meeting/minutes evidence", []),
        ("dental_program", 0.87, ["dental", "dentist", "clinic"], "dental evidence", []),
        ("finance_treasurer_records", 0.86, ["treasurer", "paypal", "receipt", "budget", "financial"], "finance evidence", []),
        ("legal_insurance_compliance", 0.86, ["incorporation", "legal", "insurance", "policy", "501c3"], "legal/insurance evidence", []),
        ("historical_photos", 0.8, ["photo", "photograph", "img_", "fastfoto", ".jpg", ".jpeg", ".png"], "photo/history evidence", []),
        ("history_archive_general", 0.65, ["history", "archive", "sunshine"], "history/archive fallback evidence", []),
    ]
    candidates = []
    for tag, confidence, needles, explanation, secondary_tags in rules:
        matches = [needle for needle in needles if needle in haystack]
        if matches:
            candidates.append(
                tag_candidate_row(
                    source_path=sample.source_path,
                    relative_path=sample.relative_path,
                    tag=tag,
                    confidence=confidence,
                    evidence=[explanation, *[f"matched:{match.strip()}" for match in matches[:3]]],
                    secondary_tags=secondary_tags,
                    assignment_source="deterministic",
                )
            )
    candidates.sort(key=lambda row: row["confidence"], reverse=True)
    deduped: list[dict[str, Any]] = []
    seen_tags: set[str] = set()
    for candidate in candidates:
        if candidate["tag"] in seen_tags:
            continue
        deduped.append(candidate)
        seen_tags.add(candidate["tag"])
    return deduped[:5]

__all__ = ["assign_tag_candidates"]
