"""Quality gate service for extraction results."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import ExtractionResult
from sunshine_extraction.sample_pipeline import extraction_quality_gate


def quality_gate_row(
    sample: SampleFile,
    extraction: ExtractionResult,
    quality: dict[str, Any],
    *,
    extraction_provider_selection: dict[str, Any] | None = None,
    extraction_validation: dict[str, Any] | None = None,
    extraction_repair: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize quality gate output for `sample-quality-gates.jsonl`."""

    validation = extraction_validation or {}
    repair = extraction_repair or {}
    provider_selection = extraction_provider_selection or {}
    return {
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
        "sample_path": str(sample.sample_path),
        "quality": quality.get("quality"),
        "can_chunk": quality.get("can_chunk"),
        "can_embed": quality.get("can_embed"),
        "requires_review": quality.get("requires_review"),
        "extraction_status": extraction.extraction_status,
        "strategy": extraction.plan.get("strategy"),
        "provider": extraction.metadata.get("provider") or provider_selection.get("selected_provider"),
        "text_length": len(extraction.text or ""),
        "validation_status": validation.get("status"),
        "validation_reason": validation.get("reason"),
        "repair_status": repair.get("status"),
        "quality_evidence": quality_evidence(extraction, quality, validation, repair),
    }


def quality_evidence(
    extraction: ExtractionResult,
    quality: dict[str, Any],
    validation: dict[str, Any],
    repair: dict[str, Any],
) -> list[str]:
    """Explain quality gate inputs for review and reports."""

    evidence = [f"quality:{quality.get('quality')}"]
    evidence.append(f"extraction_status:{extraction.extraction_status}")
    if quality.get("requires_review"):
        evidence.append("requires_review:true")
    if validation.get("status"):
        evidence.append(f"validation:{validation.get('status')}")
    if validation.get("reason"):
        evidence.append(f"validation_reason:{validation.get('reason')}")
    if repair.get("status"):
        evidence.append(f"repair:{repair.get('status')}")
    ocr_document = extraction.metadata.get("ocr_document")
    if isinstance(ocr_document, dict):
        if ocr_document.get("quality"):
            evidence.append(f"ocr_quality:{ocr_document.get('quality')}")
        if ocr_document.get("mean_confidence") is not None:
            evidence.append(f"ocr_mean_confidence:{ocr_document.get('mean_confidence')}")
    if not extraction.text.strip() and extraction.metadata:
        evidence.append("metadata_only_candidate")
    return evidence
