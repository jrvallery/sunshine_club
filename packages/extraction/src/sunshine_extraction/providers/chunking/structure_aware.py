"""Structure-aware in-house chunking provider boundary.

This currently wraps the in-house chunker while preserving a distinct provider
name for future Docling/section/table-aware chunking benchmarks.
"""

from __future__ import annotations

from typing import Any

from sunshine_extraction.providers.chunking.base import ChunkingProviderAttempt
from sunshine_extraction.providers.chunking.current import CurrentChunkingProvider
from sunshine_extraction.services.extraction import ExtractionResult


class StructureAwareChunkingProvider:
    provider_name = "structure_aware"

    def __init__(self) -> None:
        self._current = CurrentChunkingProvider()

    def dependency_status(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "available": True,
            "local_only": True,
            "implementation": "current_in_house_wrapper",
        }

    def chunk(self, extraction: ExtractionResult, quality: dict[str, Any]) -> tuple[list[dict[str, Any]], ChunkingProviderAttempt]:
        chunks, attempt = self._current.chunk(extraction, quality)
        rows = [{**chunk, "chunking_provider": self.provider_name} for chunk in chunks]
        return rows, ChunkingProviderAttempt(
            provider=self.provider_name,
            status=attempt.status,
            chunk_count=attempt.chunk_count,
            chunking_strategy=attempt.chunking_strategy,
            warnings=attempt.warnings,
            metadata={**attempt.metadata, "wrapped_provider": attempt.provider},
        )


__all__ = ["StructureAwareChunkingProvider"]
