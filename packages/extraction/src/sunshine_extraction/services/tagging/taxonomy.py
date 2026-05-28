"""Taxonomy loading service boundary."""

from __future__ import annotations

import json
from pathlib import Path

from sunshine_extraction.domain.taxonomy import TaxonomyOptions

DEFAULT_TAXONOMY_PATH = Path("docs/Sunshine_Taxonomy_Seed_v0.1_2026-05-25.json")

def load_taxonomy_options(path: str | Path) -> TaxonomyOptions:
    taxonomy_path = Path(path)
    if not taxonomy_path.is_absolute():
        taxonomy_path = Path.cwd() / taxonomy_path
    payload = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    primary_tags = [row["tag_key"] for row in payload.get("primary_tags", []) if row.get("tag_key")]
    primary_definitions = {
        row["tag_key"]: row.get("definition", "")
        for row in payload.get("primary_tags", [])
        if row.get("tag_key")
    }
    secondary_tags: list[str] = []
    for section in ("record_types", "functions", "usage_tags"):
        secondary_tags.extend(row["key"] for row in payload.get(section, []) if row.get("key"))
    return TaxonomyOptions(
        primary_tags=primary_tags,
        secondary_tags=sorted(dict.fromkeys(secondary_tags)),
        primary_definitions=primary_definitions,
    )

__all__ = ["DEFAULT_TAXONOMY_PATH", "TaxonomyOptions", "load_taxonomy_options"]
