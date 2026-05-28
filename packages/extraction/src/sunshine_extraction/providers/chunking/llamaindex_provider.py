"""Optional LlamaIndex chunking provider boundary."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.providers.chunking.base import ChunkingProviderAttempt
from sunshine_extraction.services.extraction import ExtractionResult


class LlamaIndexChunkingProvider:
    provider_name = "llamaindex"

    def dependency_status(self) -> dict[str, Any]:
        try:
            import llama_index  # noqa: F401
        except Exception as error:  # noqa: BLE001
            return {
                "provider": self.provider_name,
                "available": False,
                "local_only": True,
                "missing": ["llama-index"],
                "error": error.__class__.__name__,
            }
        return {"provider": self.provider_name, "available": True, "local_only": True}

    def chunk(self, extraction: ExtractionResult, quality: dict[str, Any]) -> tuple[list[dict[str, Any]], ChunkingProviderAttempt]:
        return [], ChunkingProviderAttempt(
            provider=self.provider_name,
            status="skipped",
            chunk_count=0,
            chunking_strategy="llamaindex_not_enabled",
            warnings=["llamaindex_chunking_not_enabled"],
            metadata={"local_only": True, "quality": quality.get("quality"), "text_length": len(extraction.text or "")},
        )


__all__ = ["LlamaIndexChunkingProvider"]
