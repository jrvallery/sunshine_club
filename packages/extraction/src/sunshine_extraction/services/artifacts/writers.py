"""Normalized artifact row writers for graph and batch outputs."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.placement import resolve_tag_placement
from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import ExtractionResult
from sunshine_extraction.services.placement import quarantine_placement_for_review_route


def sample_input_row(sample: SampleFile, corrected: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_path": str(sample.sample_path),
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
        "sample_group": sample.sample_group,
        "sample_number": sample.sample_number,
        "final_class": corrected["final_class"],
        "final_status": corrected["final_status"],
        "extraction_strategy": plan["strategy"],
    }


def extraction_result_row(extraction: ExtractionResult, quality: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_path": str(extraction.sample.sample_path),
        "source_path": extraction.sample.source_path,
        "relative_path": extraction.sample.relative_path,
        "extraction_strategy": extraction.plan["strategy"],
        "extraction_status": extraction.extraction_status,
        "quality": quality["quality"],
        "text": extraction.text,
        "metadata": extraction.metadata,
        "page_count": extraction.page_count,
        "warnings": extraction.warnings,
    }


def write_pipeline_result(
    sample: SampleFile,
    corrected: dict[str, Any],
    plan: dict[str, Any],
    extraction: ExtractionResult,
    quality: dict[str, Any],
    chunks: list[dict[str, Any]],
    embeddings: list[dict[str, Any]],
    tag_candidates: list[dict[str, Any]],
    route: dict[str, Any],
    llm_inspection: dict[str, Any],
    confidence_calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    top = tag_candidates[0] if tag_candidates else None
    embedding_statuses = sorted({row["embedding_status"] for row in embeddings})
    placement = resolve_tag_placement(
        top["tag"] if top else None,
        relative_path=sample.relative_path,
        source_path=sample.source_path,
        filename=sample.sample_path.name,
        text=extraction.text,
        metadata=extraction.metadata,
    )
    placement = quarantine_placement_for_review_route(placement, route)
    return {
        "sample_path": str(sample.sample_path),
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
        "sample_group": sample.sample_group,
        "final_class": corrected["final_class"],
        "document_subtype": plan.get("document_subtype"),
        "extraction_strategy": plan["strategy"],
        "extraction_status": extraction.extraction_status,
        "quality": quality["quality"],
        "ocr_status": extraction.metadata.get("ocr_document", {}).get("ocr_status") if isinstance(extraction.metadata.get("ocr_document"), dict) else None,
        "ocr_mean_confidence": extraction.metadata.get("ocr_document", {}).get("mean_confidence") if isinstance(extraction.metadata.get("ocr_document"), dict) else None,
        "chunk_count": len(chunks),
        "embedding_status": ",".join(embedding_statuses) if embedding_statuses else "none",
        "top_tag_candidate": top["tag"] if top else None,
        "tag_confidence": top["confidence"] if top else None,
        "tag_evidence": top["evidence"] if top else [],
        "competing_tags": tag_candidates[1:5],
        "secondary_tags": top.get("secondary_tags", []) if top else [],
        "tag_assignment_source": top.get("assignment_source") if top else None,
        "placement": placement,
        "destination_path": placement.get("destination_path"),
        "placement_status": placement.get("placement_status"),
        "placement_rule": placement.get("placement_rule"),
        "placement_date_confidence": placement.get("date_confidence"),
        "default_privacy": placement.get("default_privacy"),
        "reviewer_role": placement.get("reviewer_role"),
        "llm_status": llm_inspection.get("llm_status"),
        "llm_provider": llm_inspection.get("provider"),
        "llm_primary_tag": llm_inspection.get("primary_tag"),
        "llm_confidence": llm_inspection.get("confidence"),
        "llm_competing_tags": llm_inspection.get("competing_tags", []),
        "llm_review_reason": llm_inspection.get("review_reason"),
        "llm_warnings": _llm_warning_list(llm_inspection),
        "confidence_inputs": {
            "top_candidate": top if top else None,
            "candidate_count": len(tag_candidates),
            "llm_confidence": llm_inspection.get("confidence"),
            "llm_needs_review": llm_inspection.get("needs_review"),
            "llm_competing_tags": llm_inspection.get("competing_tags", []),
            "llm_review_reason": llm_inspection.get("review_reason"),
        },
        "confidence_calibration": confidence_calibration or {},
        "ocr_evidence": _ocr_evidence(extraction),
        "route_status": route["route_status"],
        "review_reason": route.get("review_reason"),
        "warnings": [*extraction.warnings, *_llm_warning_list(llm_inspection)],
    }


def _ocr_evidence(extraction: ExtractionResult) -> dict[str, Any]:
    fallback_used = _first_warning_value(extraction.warnings, "ocr_fallback_used:")
    model_used = _first_warning_value(extraction.warnings, "ocr_model_used:")
    return {
        "fallback_used": bool(fallback_used),
        "fallback_provider": fallback_used,
        "model_provider": model_used,
        "fallback_reason": _first_warning_value(extraction.warnings, "ocr_fallback_reason:"),
        "original_text_snippet": _first_warning_value(extraction.warnings, "ocr_original_snippet:"),
        "fallback_text_snippet": _first_warning_value(extraction.warnings, "ocr_fallback_snippet:"),
    }


def _first_warning_value(warnings: list[str], prefix: str) -> str | None:
    for warning in warnings:
        if warning.startswith(prefix):
            return warning.removeprefix(prefix)
    return None


def _llm_warning_list(llm_inspection: dict[str, Any]) -> list[str]:
    warnings = [str(warning) for warning in llm_inspection.get("warnings", []) if warning]
    if llm_inspection.get("warning"):
        warnings.append(str(llm_inspection["warning"]))
    return sorted(dict.fromkeys(warnings))
