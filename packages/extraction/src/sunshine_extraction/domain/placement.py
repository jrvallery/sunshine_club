"""Placement proposal contract for taxonomy-driven filing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class PlacementProposal:
    source_path: str
    relative_path: str
    sample_path: str
    primary_tag: str | None
    proposal: dict[str, Any]
    metadata: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        return asdict(self)
