"""Current LLM tag inspection provider wrapper."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.providers.llm.base import LLMTagInspectionAttempt
from sunshine_extraction.providers.llm.cache import llm_cache_key
from sunshine_extraction.services.cache import SQLiteModelCallCache
from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import ExtractionResult
from sunshine_extraction.services.tagging import LLMTagInspector, TaxonomyOptions, build_llm_tag_prompt


class CurrentLLMTagInspectionProvider:
    provider_name = "current"

    def __init__(self, inspector: LLMTagInspector, *, cache: SQLiteModelCallCache | None = None) -> None:
        self.inspector = inspector
        self.cache = cache

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
        cache_key = self._cache_key(
            sample=sample,
            corrected=corrected,
            plan=plan,
            extraction=extraction,
            taxonomy=taxonomy,
            deterministic_candidates=deterministic_candidates,
            semantic_examples=semantic_examples or [],
        )
        if self.cache is not None:
            cached = self.cache.get_json("llm_tag_inspection", cache_key)
            if cached:
                self.cache.record_hit("llm_tag_inspection", cache_key)
                return _cached_inspection_attempt(cached)

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
        if self.cache is not None and attempt.status in {"inspected", "inspected_with_invalid_fields", "invalid", "skipped"}:
            self.cache.set_json(
                "llm_tag_inspection",
                cache_key,
                {
                    "inspection": inspection,
                    "attempt": attempt.as_row(),
                },
            )
        return inspection, attempt

    def _cache_key(
        self,
        *,
        sample: SampleFile,
        corrected: dict[str, Any],
        plan: dict[str, Any],
        extraction: ExtractionResult,
        taxonomy: TaxonomyOptions,
        deterministic_candidates: list[dict[str, Any]],
        semantic_examples: list[dict[str, Any]],
    ) -> str:
        prompt = build_llm_tag_prompt(sample, corrected, plan, extraction, taxonomy, deterministic_candidates, semantic_examples)
        return llm_cache_key(
            prompt=prompt,
            provider=str(getattr(self.inspector, "provider_name", "disabled")),
            model=str(getattr(self.inspector, "model", "disabled")),
            schema_version="tag-inspection-v1",
        )


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


def _cached_inspection_attempt(payload: dict[str, Any]) -> tuple[dict[str, Any], LLMTagInspectionAttempt]:
    inspection = dict(payload.get("inspection") or {})
    inspection["cache_status"] = "hit"
    attempt_payload = dict(payload.get("attempt") or {})
    metadata = dict(attempt_payload.get("metadata") or {})
    metadata["cache_hit"] = True
    attempt = LLMTagInspectionAttempt(
        provider=str(attempt_payload.get("provider") or inspection.get("provider") or "unknown"),
        model=str(attempt_payload.get("model") or inspection.get("model") or "unknown"),
        status=str(attempt_payload.get("status") or inspection.get("llm_status") or "unknown"),
        warnings=list(attempt_payload.get("warnings") or []),
        input_tokens=_optional_int(attempt_payload.get("input_tokens")),
        output_tokens=_optional_int(attempt_payload.get("output_tokens")),
        total_tokens=_optional_int(attempt_payload.get("total_tokens")),
        metadata=metadata,
    )
    return inspection, attempt
