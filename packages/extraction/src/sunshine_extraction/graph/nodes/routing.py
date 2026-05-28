"""Route-or-review decision node."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.graph.state import DocumentPipelineState
from sunshine_extraction.services.routing import resolve_route_or_review


def _resolve_route_or_review_node(state: DocumentPipelineState) -> dict[str, Any]:
    if "embedding_quality_unavailable" in state.get("warnings", []):
        route = {
            "route_status": "review_embedding_unavailable",
            "review_reason": "embedding_quality_unavailable",
        }
    else:
        route = resolve_route_or_review(
            state.get("tag_candidates", []),
            state.get("extraction_quality", {"quality": "failed"}),
            state["extraction_plan"],
        )
    return {"route": route, "route_decision": _route_decision_row(state, route)}


def _route_decision_row(state: DocumentPipelineState, route: dict[str, Any]) -> dict[str, Any]:
    route_status = str(route.get("route_status") or "unknown")
    review_reason = route.get("review_reason")
    return {
        "source_path": state["sample"].source_path,
        "relative_path": state["sample"].relative_path,
        "sample_path": str(state["sample"].sample_path),
        "route_status": route_status,
        "review_reason": review_reason,
        "priority": _priority(route_status, review_reason),
        "review_stage": _review_stage(route_status, review_reason),
        "accepted": route_status == "route_candidate",
        "evidence": _route_evidence(state, route),
        "metadata": {
            "quality": state.get("extraction_quality", {}).get("quality"),
            "strategy": state.get("extraction_plan", {}).get("strategy"),
            "top_tag": (state.get("tag_candidates") or [{}])[0].get("tag") if state.get("tag_candidates") else None,
            "tag_confidence": (state.get("tag_candidates") or [{}])[0].get("confidence") if state.get("tag_candidates") else None,
            "placement_status": state.get("placement_proposal", {}).get("proposal", {}).get("placement_status"),
            "embedding_statuses": sorted({row.get("embedding_status") for row in state.get("embeddings", []) if row.get("embedding_status")}),
        },
    }


def _priority(route_status: str, review_reason: object) -> str:
    reason = str(review_reason or "")
    if route_status == "route_candidate":
        return "none"
    if "failed" in route_status or "missing" in reason:
        return "high"
    if "ocr" in route_status or "quality" in reason or "embedding" in reason:
        return "high"
    if "confidence" in route_status or "tag" in reason:
        return "medium"
    return "normal"


def _review_stage(route_status: str, review_reason: object) -> str:
    reason = str(review_reason or "")
    if route_status == "route_candidate":
        return "accepted"
    if "ocr" in route_status or "extraction" in route_status or "quality" in reason:
        return "needs_ocr_review"
    if "tag" in route_status or "confidence" in reason:
        return "needs_tag_review"
    if "placement" in route_status or "date" in reason:
        return "needs_placement_review"
    if "technical" in route_status or "deferred" in route_status:
        return "needs_technical_review"
    return "needs_triage"


def _route_evidence(state: DocumentPipelineState, route: dict[str, Any]) -> list[str]:
    evidence = [f"route_status:{route.get('route_status')}"]
    if route.get("review_reason"):
        evidence.append(f"review_reason:{route.get('review_reason')}")
    quality = state.get("extraction_quality", {})
    if quality.get("quality"):
        evidence.append(f"quality:{quality.get('quality')}")
    if quality.get("requires_review"):
        evidence.append("quality_requires_review:true")
    validation = state.get("extraction_validation", {})
    if validation.get("status"):
        evidence.append(f"validation:{validation.get('status')}")
    repair = state.get("extraction_repair", {})
    if repair.get("status"):
        evidence.append(f"repair:{repair.get('status')}")
    top = state.get("tag_candidates", [None])[0] if state.get("tag_candidates") else None
    if isinstance(top, dict):
        if top.get("tag"):
            evidence.append(f"top_tag:{top.get('tag')}")
        if top.get("confidence") is not None:
            evidence.append(f"tag_confidence:{top.get('confidence')}")
        if top.get("requires_review"):
            evidence.append("tag_requires_review:true")
    placement = state.get("placement_proposal", {}).get("proposal", {})
    if placement.get("placement_status"):
        evidence.append(f"placement_status:{placement.get('placement_status')}")
    if "embedding_quality_unavailable" in state.get("warnings", []):
        evidence.append("warning:embedding_quality_unavailable")
    return evidence
