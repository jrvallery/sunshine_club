"""Current in-house chunking provider wrapper."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.providers.chunking.base import ChunkingProviderAttempt
from sunshine_extraction.providers.chunking.legacy import chunk_content
from sunshine_extraction.services.extraction import ExtractionResult


class CurrentChunkingProvider:
    provider_name = "current"

    def dependency_status(self) -> dict[str, Any]:
        return {"provider": self.provider_name, "available": True, "local_only": True}

    def chunk(self, extraction: ExtractionResult, quality: dict[str, Any]) -> tuple[list[dict[str, Any]], ChunkingProviderAttempt]:
        chunks = [
            {
                **chunk,
                "chunking_provider": self.provider_name,
                "chunking_strategy": _chunking_strategy(extraction, quality),
            }
            for chunk in chunk_content(extraction, quality)
        ]
        return chunks, ChunkingProviderAttempt(
            provider=self.provider_name,
            status="chunked" if chunks else "skipped",
            chunk_count=len(chunks),
            chunking_strategy=_chunking_strategy(extraction, quality),
            warnings=[] if quality.get("can_chunk") else ["quality_gate_blocked_chunking"],
            metadata={
                "local_only": True,
                "quality": quality.get("quality"),
                "can_chunk": bool(quality.get("can_chunk")),
                "text_length": len(extraction.text or ""),
            },
        )


def _chunking_strategy(extraction: ExtractionResult, quality: dict[str, Any]) -> str:
    if not quality.get("can_chunk"):
        return "blocked_by_quality_gate"
    if extraction.text.strip():
        return "fixed_size_text"
    return "metadata_fallback"
