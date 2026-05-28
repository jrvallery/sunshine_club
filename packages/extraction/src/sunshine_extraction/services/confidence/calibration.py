"""Confidence calibration service for tag routing decisions."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.sample_pipeline import calibrate_tag_confidence


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
