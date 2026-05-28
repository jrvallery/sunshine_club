"""Route-or-review decision policy."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.domain.routing import RouteDecision
from sunshine_extraction.services.content import SampleFile


def resolve_route_or_review(tag_candidates: list[dict[str, Any]], quality: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Resolve whether a file can be routed or needs human/technical review."""

    if plan["strategy"] == "deferred_technical":
        return {"route_status": "technical_followup", "review_reason": plan.get("defer_reason")}
    if quality["quality"] == "deferred":
        return {"route_status": "review_or_extraction_deferred", "review_reason": "extractor_deferred"}
    if quality["quality"] == "failed":
        return {"route_status": "review_failed_extraction", "review_reason": "extraction_failed"}
    if quality["quality"] == "poor":
        if plan.get("strategy") != "ocr_page_level":
            return {"route_status": "review_text_quality", "review_reason": "text_quality_not_trusted"}
        return {"route_status": "review_ocr_quality", "review_reason": "ocr_quality_not_trusted"}
    if plan["strategy"] == "ocr_page_level" and quality["quality"] == "metadata_only":
        return {"route_status": "review_ocr_no_text", "review_reason": "ocr_text_empty"}
    if not tag_candidates:
        return {"route_status": "review_no_tag_candidate", "review_reason": "no_tag_candidate"}

    top = tag_candidates[0]
    if top.get("requires_review"):
        return {
            "route_status": "review_tag_confidence_calibration",
            "review_reason": top.get("calibrated_review_reason") or "confidence_calibration_requires_review",
        }
    if top["confidence"] >= 0.85:
        return {"route_status": "route_candidate", "review_reason": None}
    if quality["quality"] == "metadata_only" and top["confidence"] >= 0.8:
        return {"route_status": "route_candidate", "review_reason": None}
    return {"route_status": "review_low_confidence_tag", "review_reason": "tag_confidence_below_threshold"}


def resolve_route_decision(
    *,
    sample: SampleFile,
    tag_candidates: list[dict[str, Any]],
    extraction_quality: dict[str, Any],
    extraction_plan: dict[str, Any],
    extraction_validation: dict[str, Any] | None = None,
    extraction_repair: dict[str, Any] | None = None,
    placement_proposal: dict[str, Any] | None = None,
    embeddings: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve final route and normalize an auditable decision row."""

    active_warnings = warnings or []
    if "embedding_quality_unavailable" in active_warnings:
        route = {
            "route_status": "review_embedding_unavailable",
            "review_reason": "embedding_quality_unavailable",
        }
    else:
        route = resolve_route_or_review(
            tag_candidates,
            extraction_quality or {"quality": "failed"},
            extraction_plan,
        )
    return route, route_decision_row(
        sample=sample,
        route=route,
        tag_candidates=tag_candidates,
        extraction_quality=extraction_quality,
        extraction_plan=extraction_plan,
        extraction_validation=extraction_validation or {},
        extraction_repair=extraction_repair or {},
        placement_proposal=placement_proposal or {},
        embeddings=embeddings or [],
        warnings=active_warnings,
    )


def route_decision_row(
    *,
    sample: SampleFile,
    route: dict[str, Any],
    tag_candidates: list[dict[str, Any]],
    extraction_quality: dict[str, Any],
    extraction_plan: dict[str, Any],
    extraction_validation: dict[str, Any],
    extraction_repair: dict[str, Any],
    placement_proposal: dict[str, Any],
    embeddings: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    route_status = str(route.get("route_status") or "unknown")
    review_reason = route.get("review_reason")
    return RouteDecision(
        source_path=sample.source_path,
        relative_path=sample.relative_path,
        sample_path=str(sample.sample_path),
        route_status=route_status,
        review_reason=review_reason,
        priority=_priority(route_status, review_reason),
        review_stage=_review_stage(route_status, review_reason),
        accepted=route_status == "route_candidate",
        evidence=_route_evidence(
            route=route,
            tag_candidates=tag_candidates,
            extraction_quality=extraction_quality,
            extraction_validation=extraction_validation,
            extraction_repair=extraction_repair,
            placement_proposal=placement_proposal,
            embeddings=embeddings,
            warnings=warnings,
        ),
        metadata={
            "quality": extraction_quality.get("quality"),
            "strategy": extraction_plan.get("strategy"),
            "top_tag": (tag_candidates or [{}])[0].get("tag") if tag_candidates else None,
            "tag_confidence": (tag_candidates or [{}])[0].get("confidence") if tag_candidates else None,
            "placement_status": placement_proposal.get("proposal", {}).get("placement_status"),
            "embedding_statuses": sorted({row.get("embedding_status") for row in embeddings if row.get("embedding_status")}),
        },
    ).as_row()


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


def _route_evidence(
    *,
    route: dict[str, Any],
    tag_candidates: list[dict[str, Any]],
    extraction_quality: dict[str, Any],
    extraction_validation: dict[str, Any],
    extraction_repair: dict[str, Any],
    placement_proposal: dict[str, Any],
    embeddings: list[dict[str, Any]],
    warnings: list[str],
) -> list[str]:
    evidence = [f"route_status:{route.get('route_status')}"]
    if route.get("review_reason"):
        evidence.append(f"review_reason:{route.get('review_reason')}")
    if extraction_quality.get("quality"):
        evidence.append(f"quality:{extraction_quality.get('quality')}")
    if extraction_quality.get("requires_review"):
        evidence.append("quality_requires_review:true")
    if extraction_validation.get("status"):
        evidence.append(f"validation:{extraction_validation.get('status')}")
    if extraction_repair.get("status"):
        evidence.append(f"repair:{extraction_repair.get('status')}")
    top = tag_candidates[0] if tag_candidates else None
    if isinstance(top, dict):
        if top.get("tag"):
            evidence.append(f"top_tag:{top.get('tag')}")
        if top.get("confidence") is not None:
            evidence.append(f"tag_confidence:{top.get('confidence')}")
        if top.get("requires_review"):
            evidence.append("tag_requires_review:true")
    placement = placement_proposal.get("proposal", {})
    if placement.get("placement_status"):
        evidence.append(f"placement_status:{placement.get('placement_status')}")
    if "embedding_quality_unavailable" in warnings:
        evidence.append("warning:embedding_quality_unavailable")
    return evidence
