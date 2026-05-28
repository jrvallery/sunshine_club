"""Taxonomy placement proposal node."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.graph.node_utils import _empty_extraction
from sunshine_extraction.graph.state import DocumentPipelineState
from sunshine_extraction.services.placement import propose_tag_placement


def _propose_placement_node(state: DocumentPipelineState) -> dict[str, Any]:
    extraction = state.get("extraction_result") or _empty_extraction(state)
    proposal = propose_tag_placement(
        state["sample"],
        extraction,
        state.get("tag_candidates", []),
        taxonomy_path=state.get("taxonomy_path"),
    )
    return {"placement_proposal": proposal}
