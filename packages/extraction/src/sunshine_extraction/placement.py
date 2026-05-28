"""Resolve taxonomy placement rules from assigned primary tags."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


DEFAULT_TAXONOMY_SEED_PATH = "docs/Sunshine_Taxonomy_Seed_v0.1_2026-05-25.json"
SUNSHINE_PLACEMENT_RULES_PATH_ENV = "SUNSHINE_PLACEMENT_RULES_PATH"
REVIEW_FOLDER = "90_Intake_Needs_Review"


@dataclass(frozen=True)
class FolderRule:
    folder_key: str
    drive_folder: str
    purpose: str
    owner_role: str | None
    default_privacy: str | None


@dataclass(frozen=True)
class PrimaryTagRule:
    tag_key: str
    display_name: str
    folder_key: str
    placement_rule: str
    date_source: str
    definition: str
    default_privacy: str | None
    reviewer_role: str | None
    auto_route: str | None


@dataclass(frozen=True)
class TaxonomyPlacementRules:
    folders: dict[str, FolderRule]
    primary_tags: dict[str, PrimaryTagRule]


def load_placement_rules(seed_path: str | Path | None = None) -> TaxonomyPlacementRules:
    active_seed_path = placement_rules_path(seed_path)
    payload = json.loads(Path(active_seed_path).read_text(encoding="utf-8"))
    folders = {
        row["folder_key"]: FolderRule(
            folder_key=row["folder_key"],
            drive_folder=row["drive_folder"],
            purpose=row.get("purpose", ""),
            owner_role=row.get("owner_role"),
            default_privacy=row.get("default_privacy"),
        )
        for row in payload.get("canonical_folders", [])
    }
    primary_tags = {
        row["tag_key"]: PrimaryTagRule(
            tag_key=row["tag_key"],
            display_name=row.get("display_name", row["tag_key"]),
            folder_key=row["folder_key"],
            placement_rule=row["placement_rule"],
            date_source=row.get("date_source", "document_date"),
            definition=row.get("definition", ""),
            default_privacy=row.get("default_privacy"),
            reviewer_role=row.get("reviewer_role"),
            auto_route=row.get("auto_route"),
        )
        for row in payload.get("primary_tags", [])
    }
    return TaxonomyPlacementRules(folders=folders, primary_tags=primary_tags)


def resolve_tag_placement(
    primary_tag: str | None,
    *,
    relative_path: str = "",
    source_path: str = "",
    filename: str = "",
    text: str = "",
    metadata: dict[str, Any] | None = None,
    seed_path: str | Path | None = None,
) -> dict[str, Any]:
    active_seed_path = placement_rules_path(seed_path)
    rules = load_placement_rules(active_seed_path)
    if not primary_tag:
        return _review_placement("missing_primary_tag", primary_tag, rule_source=active_seed_path)
    tag_rule = rules.primary_tags.get(primary_tag)
    if tag_rule is None:
        return _review_placement("unknown_primary_tag", primary_tag, rule_source=active_seed_path)
    folder = rules.folders.get(tag_rule.folder_key)
    if folder is None:
        return _review_placement("missing_folder_mapping", primary_tag, tag_rule=tag_rule, rule_source=active_seed_path)

    placement: dict[str, Any] = {
        "primary_tag": primary_tag,
        "folder_key": tag_rule.folder_key,
        "drive_folder": folder.drive_folder,
        "placement_rule": tag_rule.placement_rule,
        "date_source": tag_rule.date_source,
        "definition": tag_rule.definition,
        "default_privacy": tag_rule.default_privacy or folder.default_privacy,
        "reviewer_role": tag_rule.reviewer_role,
        "auto_route_policy": tag_rule.auto_route,
        "placement_rule_source": active_seed_path,
        "placement_rule_id": f"{primary_tag}:{tag_rule.placement_rule}",
        "placement_status": "resolved",
        "review_reason": None,
        "date_evidence": [],
    }

    if tag_rule.placement_rule == "flat":
        placement["destination_path"] = folder.drive_folder
        placement["date_confidence"] = "not_required"
        return placement

    inferred = infer_placement_date(
        metadata or {},
        date_source=tag_rule.date_source,
        relative_path=relative_path,
        source_path=source_path,
        filename=filename,
        text=text,
    )
    placement.update(
        {
            "placement_year": inferred["year"],
            "placement_month": inferred["month"],
            "placement_year_label": inferred["year_label"],
            "date_confidence": inferred["confidence"],
            "date_evidence": inferred["evidence"],
        }
    )
    if inferred["year_label"] is None:
        placement.update(
            {
                "destination_path": f"{REVIEW_FOLDER}/{folder.drive_folder}",
                "placement_status": "needs_review",
                "review_reason": f"missing_{tag_rule.date_source}",
            }
        )
        return placement

    if tag_rule.placement_rule == "by_year":
        placement["destination_path"] = f"{folder.drive_folder}/{inferred['year_label']}"
        return placement
    if tag_rule.placement_rule == "by_year_month":
        if inferred["month"] is None:
            placement.update(
                {
                    "destination_path": f"{REVIEW_FOLDER}/{folder.drive_folder}/{inferred['year_label']}",
                    "placement_status": "needs_review",
                    "review_reason": f"missing_month_for_{tag_rule.date_source}",
                }
            )
            return placement
        placement["destination_path"] = f"{folder.drive_folder}/{inferred['year']}/{int(inferred['month']):02d}"
        return placement

    return _review_placement("unsupported_placement_rule", primary_tag, tag_rule=tag_rule, rule_source=active_seed_path)


def placement_rules_path(seed_path: str | Path | None = None) -> str:
    if seed_path is not None:
        return str(seed_path)
    configured = os.environ.get(SUNSHINE_PLACEMENT_RULES_PATH_ENV, "").strip()
    return configured or DEFAULT_TAXONOMY_SEED_PATH


def infer_placement_date(
    metadata: dict[str, Any],
    *,
    date_source: str,
    relative_path: str = "",
    source_path: str = "",
    filename: str = "",
    text: str = "",
) -> dict[str, Any]:
    metadata_value = metadata.get(date_source)
    parsed = _parse_date(metadata_value)
    if parsed:
        return {
            "year": parsed.year,
            "month": parsed.month,
            "year_label": str(parsed.year),
            "confidence": "high",
            "evidence": [f"metadata:{date_source}:{metadata_value}"],
        }

    path_text = " ".join([relative_path, source_path, filename])
    explicit_range = _find_year_range(path_text)
    if explicit_range:
        start, end, evidence = explicit_range
        return {
            "year": start,
            "month": None,
            "year_label": f"{start}-{end}",
            "confidence": "high",
            "evidence": [f"path_year_range:{evidence}"],
        }

    path_year_month = _find_year_month(path_text)
    if path_year_month:
        year, month, evidence = path_year_month
        return {
            "year": year,
            "month": month,
            "year_label": str(year),
            "confidence": "high",
            "evidence": [f"path_year_month:{evidence}"],
        }

    path_year = _find_year(path_text)
    if path_year:
        year, evidence = path_year
        return {
            "year": year,
            "month": None,
            "year_label": str(year),
            "confidence": "medium_high",
            "evidence": [f"path_year:{evidence}"],
        }

    text_year_month = _find_year_month(text[:5000])
    if text_year_month:
        year, month, evidence = text_year_month
        return {
            "year": year,
            "month": month,
            "year_label": str(year),
            "confidence": "medium",
            "evidence": [f"text_year_month:{evidence}"],
        }

    text_year = _find_year(text[:5000])
    if text_year:
        year, evidence = text_year
        return {
            "year": year,
            "month": None,
            "year_label": str(year),
            "confidence": "medium",
            "evidence": [f"text_year:{evidence}"],
        }

    return {"year": None, "month": None, "year_label": None, "confidence": "missing", "evidence": []}


def _review_placement(reason: str, primary_tag: str | None, *, tag_rule: PrimaryTagRule | None = None, rule_source: str | None = None) -> dict[str, Any]:
    return {
        "primary_tag": primary_tag,
        "folder_key": tag_rule.folder_key if tag_rule else "90_intake_needs_review",
        "drive_folder": REVIEW_FOLDER,
        "placement_rule": tag_rule.placement_rule if tag_rule else "flat",
        "date_source": tag_rule.date_source if tag_rule else None,
        "definition": tag_rule.definition if tag_rule else None,
        "default_privacy": "restricted",
        "reviewer_role": tag_rule.reviewer_role if tag_rule else "verdify_admin",
        "auto_route_policy": tag_rule.auto_route if tag_rule else None,
        "placement_rule_source": rule_source or placement_rules_path(),
        "placement_rule_id": f"{primary_tag}:{tag_rule.placement_rule}" if primary_tag and tag_rule else None,
        "destination_path": REVIEW_FOLDER,
        "placement_status": "needs_review",
        "review_reason": reason,
        "date_confidence": "missing",
        "date_evidence": [],
    }


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return datetime.fromisoformat(stripped.replace("Z", "+00:00")).date()
        except ValueError:
            pass
        match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2})[-_/](0?[1-9]|1[0-2])[-_/](0?[1-9]|[12]\d|3[01])\b", stripped)
        if match:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def _find_year_range(text: str) -> tuple[int, int, str] | None:
    for match in re.finditer(r"\b(18\d{2}|19\d{2}|20\d{2})\s*[-_]\s*(\d{2}|18\d{2}|19\d{2}|20\d{2})\b", text):
        start = int(match.group(1))
        raw_end = match.group(2)
        end = int(raw_end) if len(raw_end) == 4 else int(str(start)[:2] + raw_end)
        if start <= end <= start + 5:
            return start, end, match.group(0)
    return None


def _find_year_month(text: str) -> tuple[int, int, str] | None:
    patterns = [
        r"\b(18\d{2}|19\d{2}|20\d{2})[-_/](0?[1-9]|1[0-2])\b",
        r"\b(0?[1-9]|1[0-2])[-_/](18\d{2}|19\d{2}|20\d{2})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        first = int(match.group(1))
        second = int(match.group(2))
        if first > 1000:
            return first, second, match.group(0)
        return second, first, match.group(0)
    month_match = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(18\d{2}|19\d{2}|20\d{2})\b",
        text,
        flags=re.IGNORECASE,
    )
    if month_match:
        month = _month_number(month_match.group(1))
        if month:
            return int(month_match.group(2)), month, month_match.group(0)
    return None


def _find_year(text: str) -> tuple[int, str] | None:
    match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2})\b", text)
    if not match:
        return None
    return int(match.group(1)), match.group(1)


def _month_number(name: str) -> int | None:
    months = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    return months.get(name.lower())


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve a Sunshine primary tag to a destination rule.")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--relative-path", default="")
    parser.add_argument("--source-path", default="")
    parser.add_argument("--filename", default="")
    parser.add_argument("--text", default="")
    parser.add_argument("--taxonomy-seed", default=DEFAULT_TAXONOMY_SEED_PATH)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = resolve_tag_placement(
        args.tag,
        relative_path=args.relative_path,
        source_path=args.source_path,
        filename=args.filename,
        text=args.text,
        seed_path=args.taxonomy_seed,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
