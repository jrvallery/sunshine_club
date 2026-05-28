"""SQLite golden-label vector store boundary."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.providers.vectorstores.base import VectorStoreUpsertResult


class SQLiteGoldenVectorStoreProvider:
    provider_name = "sqlite_golden"

    def __init__(self, *, index_path: str | None = None) -> None:
        self.index_path = index_path

    def dependency_status(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "available": bool(self.index_path),
            "local_only": True,
            "index_path": self.index_path,
        }

    def upsert_embeddings(self, chunks: list[dict[str, Any]], embeddings: list[dict[str, Any]]) -> VectorStoreUpsertResult:
        return VectorStoreUpsertResult(
            provider=self.provider_name,
            collection=self.index_path,
            status="skipped",
            indexed_count=0,
            skipped_count=len(embeddings),
            indexed_chunk_ids=[],
            skipped_chunk_ids=[str(row.get("chunk_id")) for row in embeddings if row.get("chunk_id")],
            warnings=["sqlite_golden_indexing_managed_by_semantic_index_builder"],
            metadata={"local_only": True, "chunk_count": len(chunks), "index_path": self.index_path},
        )
