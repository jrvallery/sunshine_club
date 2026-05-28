"""Current LLM tag inspection provider wrapper."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.providers.llm.base import LLMTagInspectionAttempt
from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import ExtractionResult
from sunshine_extraction.services.tagging import LLMTagInspector, TaxonomyOptions


class CurrentLLMTagInspectionProvider:
    provider_name = "current"

    def __init__(self, inspector: LLMTagInspector) -> None:
        self.inspector = inspector

    def dependency_status(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "llm_provider": getattr(self.inspector, "provider_name", "disabled"),
            "model": getattr(self.inspector, "model", "disabled"),
            "available": True,
            "local_only": getattr(self.inspector, "provider_name", "disabled") not in {"openai", "gemini", "google"},
        }

    def inspect_tags(
        self,
        *,
        sample: SampleFile,
        corrected: dict[str, Any],
        plan: dict[str, Any],
        extraction: ExtractionResult,
        taxonomy: TaxonomyOptions,
        deterministic_candidates: list[dict[str, Any]],
        semantic_examples: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], LLMTagInspectionAttempt]:
        inspection = self.inspector.inspect(
            sample=sample,
            corrected=corrected,
            plan=plan,
            extraction=extraction,
            taxonomy=taxonomy,
            deterministic_candidates=deterministic_candidates,
            semantic_examples=semantic_examples or [],
        )
        warnings = _llm_inspection_warnings(inspection)
        attempt = LLMTagInspectionAttempt(
            provider=str(inspection.get("provider") or getattr(self.inspector, "provider_name", "disabled")),
            model=str(inspection.get("model") or getattr(self.inspector, "model", "disabled")),
            status=str(inspection.get("llm_status") or "unknown"),
            warnings=warnings,
            input_tokens=_optional_int(inspection.get("input_tokens")),
            output_tokens=_optional_int(inspection.get("output_tokens")),
            total_tokens=_optional_int(inspection.get("total_tokens")),
            metadata={
                "local_only": str(inspection.get("provider") or "") not in {"openai", "gemini", "google"},
                "primary_tag": inspection.get("primary_tag"),
                "confidence": inspection.get("confidence"),
                "needs_review": inspection.get("needs_review"),
                "review_reason": inspection.get("review_reason"),
            },
        )
        return inspection, attempt


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    return None


def _llm_inspection_warnings(inspection: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    raw_warnings = inspection.get("warnings")
    if isinstance(raw_warnings, list):
        warnings.extend(str(warning) for warning in raw_warnings if str(warning).strip())
    warning = inspection.get("warning")
    if warning:
        warnings.append(str(warning))
    if inspection.get("llm_status") == "failed" and not warnings:
        warnings.append("llm_tag_inspection_failed")
    unique: list[str] = []
    for warning_value in warnings:
        if warning_value not in unique:
            unique.append(warning_value)
    return unique
