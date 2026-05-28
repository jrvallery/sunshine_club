"""Embedding and vectorization service boundary."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingProvider,
    EmbeddingProviderError,
    PlaceholderEmbeddingProvider,
    embed_texts,
)


def embed_chunks(chunks: list[dict[str, Any]], provider: EmbeddingProvider) -> list[dict[str, Any]]:
    """Embed chunk text and return backward-compatible embedding rows."""

    if not chunks:
        return []
    results = embed_texts([chunk["text"] for chunk in chunks], provider)
    rows = []
    for chunk, result in zip(chunks, results, strict=True):
        row = result.as_row()
        row.update({"source_path": chunk["source_path"], "relative_path": chunk["relative_path"], "chunk_id": chunk["chunk_id"]})
        rows.append(row)
    return rows


def embed_chunks_with_fallback(chunks: list[dict[str, Any]], provider: EmbeddingProvider) -> tuple[list[dict[str, Any]], list[str]]:
    """Embed chunks, falling back to deterministic placeholder embeddings for dev/test mode."""

    try:
        return embed_chunks(chunks, provider), []
    except (EmbeddingConfigurationError, EmbeddingProviderError):
        return embed_chunks(chunks, PlaceholderEmbeddingProvider()), ["embedding_provider_failed_fell_back_to_placeholder"]

__all__ = ["embed_chunks", "embed_chunks_with_fallback"]
