"""Tag candidate contracts used by deterministic, semantic, and LLM evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TagCandidate:
    source_path: str | None
    relative_path: str | None
    tag: str
    confidence: float
    evidence: list[str]
    secondary_tags: list[str]
    assignment_source: str
    requires_review: bool | None = None
    calibrated_review_reason: str | None = None
    metadata: dict[str, Any] | None = None

    def as_row(self) -> dict[str, Any]:
        row = asdict(self)
        if self.requires_review is None:
            row.pop("requires_review")
        if self.calibrated_review_reason is None:
            row.pop("calibrated_review_reason")
        if self.metadata is None:
            row.pop("metadata")
        return row


def tag_candidate_row(
    *,
    source_path: str | None,
    relative_path: str | None,
    tag: str,
    confidence: float,
    evidence: list[str],
    secondary_tags: list[str] | None = None,
    assignment_source: str,
    requires_review: bool | None = None,
    calibrated_review_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return TagCandidate(
        source_path=source_path,
        relative_path=relative_path,
        tag=tag,
        confidence=confidence,
        evidence=evidence,
        secondary_tags=secondary_tags or [],
        assignment_source=assignment_source,
        requires_review=requires_review,
        calibrated_review_reason=calibrated_review_reason,
        metadata=metadata,
    ).as_row()
