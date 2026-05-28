"""Confidence calibration service for tag routing decisions."""

from __future__ import annotations

from typing import Any


def calibrate_confidence(
    tag_candidates: list[dict[str, Any]],
    quality: dict[str, Any],
    plan: dict[str, Any],
    *,
    llm_inspection: dict[str, Any] | None = None,
    semantic_examples: list[dict[str, Any]] | None = None,
    embeddings: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Calibrate candidate confidence and produce review-gate factors."""

    return calibrate_tag_confidence(
        tag_candidates,
        quality,
        plan,
        llm_inspection=llm_inspection,
        semantic_examples=semantic_examples,
        embeddings=embeddings,
    )


def calibrate_tag_confidence(
    tag_candidates: list[dict[str, Any]],
    quality: dict[str, Any],
    plan: dict[str, Any],
    *,
    llm_inspection: dict[str, Any] | None = None,
    semantic_examples: list[dict[str, Any]] | None = None,
    embeddings: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not tag_candidates:
        return [], {
            "status": "no_candidates",
            "base_confidence": None,
            "calibrated_confidence": None,
            "factors": ["no_tag_candidates"],
            "requires_review": True,
            "review_reason": "no_tag_candidate",
        }

    calibrated = [dict(candidate) for candidate in tag_candidates]
    top = calibrated[0]
    base_confidence = float(top.get("confidence") or 0)
    confidence = base_confidence
    factors: list[str] = []
    requires_review = False
    review_reason: str | None = None

    quality_value = str(quality.get("quality") or "unknown")
    if quality.get("requires_review") or quality_value in {"poor", "failed", "deferred", "empty"}:
        confidence = min(confidence, 0.74)
        factors.append(f"extraction_quality_requires_review:{quality_value}")
        requires_review = True
        review_reason = "extraction_quality_not_trusted"

    if plan.get("strategy") == "ocr_page_level" and quality_value == "metadata_only":
        confidence = min(confidence, 0.79)
        factors.append("ocr_metadata_only")
        requires_review = True
        review_reason = "ocr_text_empty"

    llm = llm_inspection or {}
    llm_primary = llm.get("primary_tag")
    llm_confidence = float(llm.get("confidence") or 0)
    if llm.get("needs_review"):
        confidence = min(confidence, 0.79)
        factors.append("llm_requested_review")
        requires_review = True
        review_reason = "llm_requested_review"
    if llm.get("llm_status") in {"failed", "invalid"}:
        confidence = min(confidence, 0.79)
        factors.append(f"llm_structured_output_unusable:{llm.get('llm_status')}")
        requires_review = True
        review_reason = llm.get("review_reason") or "llm_structured_output_unusable"
    elif llm.get("llm_status") == "inspected_with_invalid_fields" or _llm_warning_list(llm):
        confidence = min(confidence, 0.79)
        factors.append("llm_structured_output_invalid_fields")
        requires_review = True
        review_reason = "llm_structured_output_invalid"
    if llm.get("llm_status") == "inspected" and llm_primary and llm_primary != top.get("tag") and llm_confidence >= 0.7:
        confidence = min(confidence, 0.78)
        factors.append(f"llm_primary_disagrees:{llm_primary}")
        requires_review = True
        review_reason = "llm_tag_disagreement"

    top_examples = (semantic_examples or [])[:3]
    if top_examples:
        matching = [example for example in top_examples if example.get("correct_primary_tag") == top.get("tag")]
        conflicting = [example for example in top_examples if example.get("correct_primary_tag") != top.get("tag")]
        strong_conflict = [example for example in conflicting if float(example.get("score") or 0) >= 0.72]
        if matching:
            factors.append(f"semantic_support:{len(matching)}")
        if strong_conflict and len(strong_conflict) >= len(matching):
            best = strong_conflict[0]
            confidence = min(confidence, 0.8)
            factors.append(f"semantic_conflict:{best.get('correct_primary_tag')}:{float(best.get('score') or 0):.3f}")
            requires_review = True
            review_reason = "semantic_example_conflict"

    embedding_statuses = {str(row.get("embedding_status") or "") for row in (embeddings or [])}
    if "placeholder" in embedding_statuses:
        factors.append("embedding_placeholder_used")

    confidence = round(max(0.0, min(confidence, 0.99)), 4)
    top["pre_calibration_confidence"] = base_confidence
    top["confidence"] = confidence
    top["confidence_calibration_factors"] = factors
    top["requires_review"] = requires_review
    top["calibrated_review_reason"] = review_reason
    top["evidence"] = [
        *top.get("evidence", []),
        *[f"confidence_calibration:{factor}" for factor in factors],
    ]
    calibrated[0] = top
    return calibrated, {
        "status": "calibrated",
        "base_confidence": base_confidence,
        "calibrated_confidence": confidence,
        "factors": factors,
        "requires_review": requires_review,
        "review_reason": review_reason,
        "top_tag": top.get("tag"),
    }


def confidence_calibration_row(
    calibration: dict[str, Any],
    *,
    source_path: str | None,
    relative_path: str | None,
    top_candidate: dict[str, Any] | None,
    quality: dict[str, Any],
    plan: dict[str, Any],
    candidate_count: int | None = None,
) -> dict[str, Any]:
    """Normalize calibration output as an auditable JSONL artifact row."""

    return {
        "source_path": source_path,
        "relative_path": relative_path,
        "status": calibration.get("status"),
        "top_tag": calibration.get("top_tag") or (top_candidate or {}).get("tag"),
        "base_confidence": calibration.get("base_confidence"),
        "calibrated_confidence": calibration.get("calibrated_confidence"),
        "requires_review": bool(calibration.get("requires_review")),
        "review_reason": calibration.get("review_reason"),
        "factors": calibration.get("factors", []),
        "quality": quality.get("quality"),
        "extraction_strategy": plan.get("strategy"),
        "candidate_count": candidate_count,
        "top_candidate": top_candidate,
    }


def _llm_warning_list(llm_inspection: dict[str, Any]) -> list[str]:
    warnings = [str(warning) for warning in llm_inspection.get("warnings", []) if warning]
    if llm_inspection.get("warning"):
        warnings.append(str(llm_inspection["warning"]))
    return sorted(dict.fromkeys(warnings))
