"""Cortex embedding provider for local OpenAI-compatible infrastructure."""

from __future__ import annotations

from sunshine_extraction.embeddings import (
    DEFAULT_CORTEX_BASE_URL,
    DEFAULT_CORTEX_EMBEDDING_DIMENSIONS,
    DEFAULT_CORTEX_EMBEDDING_MODEL,
    OpenAICompatibleEmbeddingProvider,
    _openai_base_url_from_cortex_base,
)


class CortexEmbeddingProvider(OpenAICompatibleEmbeddingProvider):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_CORTEX_EMBEDDING_MODEL,
        base_url: str = DEFAULT_CORTEX_BASE_URL,
        dimensions: int = DEFAULT_CORTEX_EMBEDDING_DIMENSIONS,
        timeout_seconds: float = 60,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=_openai_base_url_from_cortex_base(base_url),
            provider_name="cortex",
            dimensions=dimensions,
            timeout_seconds=timeout_seconds,
        )


__all__ = ["CortexEmbeddingProvider"]
