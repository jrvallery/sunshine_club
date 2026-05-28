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


def parser_result_row(
    extraction: ExtractionResult,
    quality: dict[str, Any],
    *,
    provider_selection: dict[str, Any] | None = None,
    provider_attempts: list[dict[str, Any]] | None = None,
    document_structure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    attempts = provider_attempts or []
    structure = document_structure or {}
    pages = structure.get("pages") if isinstance(structure.get("pages"), list) else []
    pages_with_text = sum(1 for page in pages if str(page.get("text") or "").strip())
    page_count = extraction.page_count or structure.get("page_count") or (len(pages) if pages else None)
    provider = _parser_provider(extraction, provider_selection or {}, attempts, structure)
    warnings = _unique_list([*extraction.warnings, *[warning for attempt in attempts for warning in attempt.get("warnings", [])]])
    return {
        "source_path": extraction.sample.source_path,
        "relative_path": extraction.sample.relative_path,
        "sample_path": str(extraction.sample.sample_path),
        "sample_group": extraction.sample.sample_group,
        "sample_number": extraction.sample.sample_number,
        "provider": provider,
        "parser_provider": provider,
        "strategy": extraction.plan.get("strategy"),
        "document_subtype": extraction.plan.get("document_subtype"),
        "status": extraction.extraction_status,
        "quality": quality.get("quality"),
        "can_chunk": quality.get("can_chunk"),
        "requires_review": quality.get("requires_review"),
        "review_reason": _parser_review_reason(quality, warnings),
        "text_length": len(extraction.text or ""),
        "text_snippet": _snippet(extraction.text or ""),
        "page_count": page_count,
        "page_structure_available": bool(pages),
        "page_text_coverage_rate": _rate(pages_with_text, len(pages)) if pages else (1.0 if extraction.text.strip() else 0.0),
        "pages_with_text": pages_with_text,
        "layout_signal_count": len(structure.get("sections", []) or []) + len(structure.get("tables", []) or []) + len(structure.get("figures", []) or []),
        "local_only": _provider_attempt_local_only(attempts),
        "warnings": warnings,
        "provider_selection": provider_selection or {},
        "provider_attempts": attempts,
        "metadata": {
            "graph_artifact": True,
            "extraction_metadata": extraction.metadata,
            "structure_metadata": structure.get("metadata", {}),
        },
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


def _parser_provider(
    extraction: ExtractionResult,
    provider_selection: dict[str, Any],
    provider_attempts: list[dict[str, Any]],
    document_structure: dict[str, Any],
) -> str:
    if provider_selection.get("selected_provider"):
        return str(provider_selection["selected_provider"])
    if extraction.metadata.get("provider"):
        return str(extraction.metadata["provider"])
    if document_structure.get("provider"):
        return str(document_structure["provider"])
    if provider_attempts:
        return str(provider_attempts[-1].get("provider") or "unknown")
    return "current"


def _parser_review_reason(quality: dict[str, Any], warnings: list[str]) -> str | None:
    if quality.get("requires_review"):
        return str(quality.get("review_reason") or quality.get("quality") or "quality_requires_review")
    if warnings:
        return None
    return None


def _provider_attempt_local_only(provider_attempts: list[dict[str, Any]]) -> bool:
    values = [attempt.get("metadata", {}).get("local_only") for attempt in provider_attempts if isinstance(attempt.get("metadata"), dict)]
    if not values:
        return True
    return all(value is not False for value in values)


def _snippet(text: str, limit: int = 320) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _unique_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result


def _llm_warning_list(llm_inspection: dict[str, Any]) -> list[str]:
    warnings = [str(warning) for warning in llm_inspection.get("warnings", []) if warning]
    if llm_inspection.get("warning"):
        warnings.append(str(llm_inspection["warning"]))
    return sorted(dict.fromkeys(warnings))
