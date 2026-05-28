"""Taxonomy option contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaxonomyOptions:
    primary_tags: list[str]
    secondary_tags: list[str]
    primary_definitions: dict[str, str]
