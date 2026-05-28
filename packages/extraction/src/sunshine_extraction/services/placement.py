"""Placement proposal services."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.domain.placement import PlacementProposal
from sunshine_extraction.placement import resolve_tag_placement
from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import ExtractionResult


def propose_tag_placement(
    sample: SampleFile,
    extraction: ExtractionResult,
    tag_candidates: list[dict[str, Any]],
    *,
    taxonomy_path: str | None = None,
) -> dict[str, Any]:
    top = tag_candidates[0] if tag_candidates else None
    primary_tag = top.get("tag") if top else None
    placement = resolve_tag_placement(
        primary_tag,
        relative_path=sample.relative_path,
        source_path=sample.source_path,
        filename=sample.sample_path.name,
        text=extraction.text,
        metadata=extraction.metadata,
        seed_path=taxonomy_path or "docs/Sunshine_Taxonomy_Seed_v0.1_2026-05-25.json",
    )
    proposal = PlacementProposal(
        source_path=sample.source_path,
        relative_path=sample.relative_path,
        sample_path=str(sample.sample_path),
        primary_tag=primary_tag,
        proposal=placement,
        metadata={
            "tag_confidence": top.get("confidence") if top else None,
            "tag_assignment_source": top.get("assignment_source") if top else None,
            "candidate_count": len(tag_candidates),
        },
    )
    return proposal.as_row()
