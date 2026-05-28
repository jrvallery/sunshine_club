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
from sunshine_extraction.providers.embeddings.cache import embedding_cache_key
from sunshine_extraction.services.cache import SQLiteModelCallCache
from sunshine_extraction.services.vectorization import embed_chunks, embed_chunks_with_fallback


class CurrentChunkEmbeddingProvider:
    provider_name = "current"

    def __init__(self, provider: EmbeddingProvider, *, cache: SQLiteModelCallCache | None = None) -> None:
        self.provider = provider
        self.cache = cache

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
        cache_hits = 0
        cache_misses = 0
        try:
            if failure_mode == "review":
                rows, cache_hits, cache_misses = self._embed_chunks_with_cache(chunks, fallback=False)
            else:
                rows, warnings, cache_hits, cache_misses = self._embed_chunks_with_fallback_cache(chunks)
        except (EmbeddingConfigurationError, EmbeddingProviderError) as error:
            rows = []
            warnings = ["embedding_provider_failed", "embedding_quality_unavailable"]
            metadata["error"] = f"{type(error).__name__}: {error}"
            cache_misses = len(chunks)

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
            metadata={**metadata, "cache_enabled": self.cache is not None, "cache_hits": cache_hits, "cache_misses": cache_misses},
        )
        return rows, attempt

    def _embed_chunks_with_fallback_cache(self, chunks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], int, int]:
        try:
            rows, cache_hits, cache_misses = self._embed_chunks_with_cache(chunks, fallback=False)
            return rows, [], cache_hits, cache_misses
        except (EmbeddingConfigurationError, EmbeddingProviderError):
            rows, cache_hits, cache_misses = self._embed_chunks_with_cache(chunks, fallback=True)
            return rows, ["embedding_provider_failed_fell_back_to_placeholder"], cache_hits, cache_misses

    def _embed_chunks_with_cache(self, chunks: list[dict[str, Any]], *, fallback: bool) -> tuple[list[dict[str, Any]], int, int]:
        if self.cache is None:
            return (embed_chunks(chunks, PlaceholderEmbeddingProvider()) if fallback else embed_chunks(chunks, self.provider), 0, len(chunks))

        provider = PlaceholderEmbeddingProvider() if fallback else self.provider
        provider_name = _provider_name(provider)
        model = str(getattr(provider, "model", "unknown"))
        dimensions = int(getattr(provider, "dimensions", 0) or 0)
        rows_by_index: dict[int, dict[str, Any]] = {}
        misses: list[tuple[int, dict[str, Any], str]] = []
        cache_hits = 0

        for index, chunk in enumerate(chunks):
            cache_key = embedding_cache_key(text=str(chunk.get("text") or ""), provider=provider_name, model=model, dimensions=dimensions)
            cached = self.cache.get_json("embedding", cache_key)
            if cached:
                self.cache.record_hit("embedding", cache_key)
                rows_by_index[index] = _embedding_row_from_cache(index, chunk, cached)
                cache_hits += 1
            else:
                misses.append((index, chunk, cache_key))

        if misses:
            embedded_rows = embed_chunks([chunk for _, chunk, _ in misses], provider)
            for (index, chunk, cache_key), row in zip(misses, embedded_rows, strict=True):
                row = {**row, "text_index": index}
                rows_by_index[index] = row
                self.cache.set_json("embedding", cache_key, _embedding_cache_payload(row))

        return [rows_by_index[index] for index in range(len(chunks))], cache_hits, len(misses)


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


def _embedding_cache_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "embedding_status": row.get("embedding_status"),
        "embedding_provider": row.get("embedding_provider"),
        "embedding_model": row.get("embedding_model"),
        "embedding_dimensions": row.get("embedding_dimensions"),
        "semantic_quality": row.get("semantic_quality"),
        "embedding": row.get("embedding"),
    }


def _embedding_row_from_cache(index: int, chunk: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        "text_index": index,
        "source_path": chunk.get("source_path"),
        "relative_path": chunk.get("relative_path"),
        "chunk_id": chunk.get("chunk_id"),
        "cache_status": "hit",
    }
