"""Route-or-review decision node."""

from __future__ import annotations

from sunshine_extraction.graph.state import DocumentPipelineState
from sunshine_extraction.services.routing import resolve_route_decision


def _resolve_route_or_review_node(state: DocumentPipelineState) -> dict[str, Any]:
    route, decision = resolve_route_decision(
        sample=state["sample"],
        tag_candidates=state.get("tag_candidates", []),
        extraction_quality=state.get("extraction_quality", {"quality": "failed"}),
        extraction_plan=state["extraction_plan"],
        extraction_validation=state.get("extraction_validation", {}),
        extraction_repair=state.get("extraction_repair", {}),
        placement_proposal=state.get("placement_proposal", {}),
        embeddings=state.get("embeddings", []),
        warnings=state.get("warnings", []),
    )
    return {"route": route, "route_decision": decision}
