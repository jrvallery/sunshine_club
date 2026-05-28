"""No-op vector store used when Qdrant is not configured."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.providers.vectorstores.base import VectorStoreUpsertResult


class NoopVectorStoreProvider:
    provider_name = "noop"

    def dependency_status(self) -> dict[str, Any]:
        return {"provider": self.provider_name, "available": True, "local_only": True}

    def upsert_embeddings(self, chunks: list[dict[str, Any]], embeddings: list[dict[str, Any]]) -> VectorStoreUpsertResult:
        semantic_embedding_ids = [str(row.get("chunk_id")) for row in embeddings if row.get("embedding_status") == "embedded" and row.get("chunk_id")]
        return VectorStoreUpsertResult(
            provider=self.provider_name,
            collection=None,
            status="skipped",
            indexed_count=0,
            skipped_count=len(semantic_embedding_ids),
            indexed_chunk_ids=[],
            skipped_chunk_ids=semantic_embedding_ids,
            warnings=["vector_store_not_configured"] if semantic_embedding_ids else [],
            metadata={
                "local_only": True,
                "chunk_count": len(chunks),
                "embedding_count": len(embeddings),
                "semantic_embedding_count": len(semantic_embedding_ids),
            },
        )
