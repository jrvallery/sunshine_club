"""Base contracts for local LLM-backed tagging providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import ExtractionResult
from sunshine_extraction.services.tagging import TaxonomyOptions


@dataclass(frozen=True)
class LLMTagInspectionAttempt:
    provider: str
    model: str
    status: str
    warnings: list[str]
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    metadata: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


class LLMTagInspectionProvider(Protocol):
    provider_name: str

    def dependency_status(self) -> dict[str, Any]:
        """Return local LLM dependency status without inspecting a document."""

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
        """Inspect tag candidates and return normalized structured output plus attempt metadata."""
