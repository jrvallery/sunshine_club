"""Index chunk embeddings with a local vector-store provider."""

from __future__ import annotations

from sunshine_extraction.providers.vectorstores import VectorStoreProvider


def index_chunks(
    chunks: list[dict],
    embeddings: list[dict],
    vector_store: VectorStoreProvider,
) -> dict:
    return vector_store.upsert_embeddings(chunks, embeddings).as_row()
