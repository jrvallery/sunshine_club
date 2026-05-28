"""Hosted OpenAI embedding provider policy boundary.

Sunshine production policy is local-only. This module exists so the provider
tree has an explicit OpenAI boundary, but construction is intentionally blocked.
"""

from __future__ import annotations

from sunshine_extraction.embeddings import EmbeddingConfigurationError


class HostedOpenAIEmbeddingProvider:
    def __init__(self, *_args, **_kwargs) -> None:
        raise EmbeddingConfigurationError("Hosted OpenAI embeddings are not allowed; use the local Cortex provider")


__all__ = ["HostedOpenAIEmbeddingProvider"]
