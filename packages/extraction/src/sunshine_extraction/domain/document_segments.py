"""Logical child-document segment contracts.

Segments let the pipeline represent page ranges inside a larger source file
without mutating or splitting the original customer document.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DocumentSegment:
    segment_id: str
    parent_file_id: str | None
    source_path: str
    relative_path: str
    sample_path: str
    page_start: int | None
    page_end: int | None
    segment_index: int
    segment_type: str
    segment_title: str | None
    segment_confidence: float
    segment_boundary_evidence: list[str]
    requires_segment_review: bool
    metadata: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        return asdict(self)

