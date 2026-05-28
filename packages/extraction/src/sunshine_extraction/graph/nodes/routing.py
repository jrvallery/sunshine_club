"""Route-or-review decision node."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.graph.state import DocumentPipelineState
from sunshine_extraction.services.routing import resolve_route_or_review


def _resolve_route_or_review_node(state: DocumentPipelineState) -> dict[str, Any]:
    if "embedding_quality_unavailable" in state.get("warnings", []):
        return {
            "route": {
                "route_status": "review_embedding_unavailable",
                "review_reason": "embedding_quality_unavailable",
            }
        }
    return {
        "route": resolve_route_or_review(
            state.get("tag_candidates", []),
            state.get("extraction_quality", {"quality": "failed"}),
            state["extraction_plan"],
        )
    }
