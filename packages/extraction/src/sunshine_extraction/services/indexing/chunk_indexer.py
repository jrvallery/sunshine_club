"""Index chunk embeddings with a local vector-store provider."""

from __future__ import annotations

from sunshine_extraction.providers.vectorstores import VectorStoreProvider


def index_chunks(
    chunks: list[dict],
    embeddings: list[dict],
    vector_store: VectorStoreProvider,
) -> dict:
    result = vector_store.upsert_embeddings(chunks, embeddings).as_row()
    result["chunk_count"] = len(chunks)
    result["embedding_count"] = len(embeddings)
    result["semantic_embedding_count"] = sum(1 for row in embeddings if row.get("embedding_status") == "embedded")
    result["placeholder_embedding_count"] = sum(1 for row in embeddings if row.get("embedding_status") == "placeholder")
    return result
