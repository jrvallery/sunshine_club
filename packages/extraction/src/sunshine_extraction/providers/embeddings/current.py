"""Current embedding provider wrapper around the existing embedding module."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingProvider,
    EmbeddingProviderError,
    PlaceholderEmbeddingProvider,
)
from sunshine_extraction.providers.embeddings.base import ChunkEmbeddingProviderAttempt
from sunshine_extraction.services.vectorization import embed_chunks, embed_chunks_with_fallback


class CurrentChunkEmbeddingProvider:
    provider_name = "current"

    def __init__(self, provider: EmbeddingProvider) -> None:
        self.provider = provider

    def dependency_status(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "embedding_provider": _provider_name(self.provider),
            "model": getattr(self.provider, "model", "unknown"),
            "dimensions": getattr(self.provider, "dimensions", None),
            "available": True,
            "local_only": _provider_name(self.provider) != "openai",
        }

    def embed_chunks(
        self,
        chunks: list[dict[str, Any]],
        *,
        failure_mode: str,
    ) -> tuple[list[dict[str, Any]], ChunkEmbeddingProviderAttempt]:
        warnings: list[str] = []
        metadata: dict[str, Any] = {
            "legacy_provider": self.provider.__class__.__name__,
            "failure_mode": failure_mode,
            "local_only": _provider_name(self.provider) != "openai",
        }
        try:
            if failure_mode == "review":
                rows = embed_chunks(chunks, self.provider)
            else:
                rows, warnings = embed_chunks_with_fallback(chunks, self.provider)
        except (EmbeddingConfigurationError, EmbeddingProviderError) as error:
            rows = []
            warnings = ["embedding_provider_failed", "embedding_quality_unavailable"]
            metadata["error"] = f"{type(error).__name__}: {error}"

        if failure_mode == "review" and _contains_placeholder(self.provider, rows):
            warnings = [*warnings, "embedding_placeholder_disallowed_in_eval", "embedding_quality_unavailable"]

        status = _status(self.provider, rows, warnings)
        attempt = ChunkEmbeddingProviderAttempt(
            provider=_provider_name(self.provider),
            model=str(getattr(self.provider, "model", "unknown")),
            status=status,
            requested_count=len(chunks),
            embedded_count=len(rows),
            dimensions=_dimensions(self.provider, rows),
            semantic_quality=bool(rows) and status == "embedded",
            warnings=_unique(warnings),
            metadata=metadata,
        )
        return rows, attempt


def _contains_placeholder(provider: EmbeddingProvider, rows: list[dict[str, Any]]) -> bool:
    return isinstance(provider, PlaceholderEmbeddingProvider) or any(row.get("embedding_status") == "placeholder" for row in rows)


def _status(provider: EmbeddingProvider, rows: list[dict[str, Any]], warnings: list[str]) -> str:
    if _contains_placeholder(provider, rows):
        return "placeholder"
    if warnings:
        return "failed"
    if rows:
        return "embedded"
    return "skipped"


def _dimensions(provider: EmbeddingProvider, rows: list[dict[str, Any]]) -> int | None:
    if rows:
        value = rows[0].get("embedding_dimensions")
        return int(value) if isinstance(value, int) else None
    value = getattr(provider, "dimensions", None)
    return int(value) if isinstance(value, int) else None


def _provider_name(provider: EmbeddingProvider) -> str:
    if isinstance(provider, PlaceholderEmbeddingProvider):
        return "local"
    return str(getattr(provider, "provider_name", "") or provider.__class__.__name__.replace("EmbeddingProvider", "").lower() or "embedding")


def _unique(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique
