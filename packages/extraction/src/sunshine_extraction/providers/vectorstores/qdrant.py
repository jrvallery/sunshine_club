"""Qdrant vector-store provider.

The qdrant-client import is intentionally lazy so tests and non-indexing local
development do not require a running Qdrant installation.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from sunshine_extraction.providers.vectorstores.base import VectorStoreUpsertResult


class QdrantVectorStoreProvider:
    provider_name = "qdrant"

    def __init__(self, *, url: str | None = None, collection: str | None = None) -> None:
        self.url = (url or os.environ.get("SUNSHINE_QDRANT_URL") or "http://127.0.0.1:6333").rstrip("/")
        self.collection = collection or os.environ.get("SUNSHINE_QDRANT_COLLECTION") or "sunshine_chunks"

    def dependency_status(self) -> dict[str, Any]:
        try:
            import qdrant_client  # noqa: F401
        except Exception as error:  # noqa: BLE001 - optional dependency probe.
            return {
                "provider": self.provider_name,
                "available": False,
                "local_only": True,
                "url": self.url,
                "collection": self.collection,
                "missing": ["qdrant-client"],
                "error": error.__class__.__name__,
            }
        return {"provider": self.provider_name, "available": True, "local_only": True, "url": self.url, "collection": self.collection}

    def upsert_embeddings(self, chunks: list[dict[str, Any]], embeddings: list[dict[str, Any]]) -> VectorStoreUpsertResult:
        embedded_rows = [row for row in embeddings if row.get("embedding_status") == "embedded" and isinstance(row.get("embedding"), list)]
        if not embedded_rows:
            return VectorStoreUpsertResult(
                provider=self.provider_name,
                collection=self.collection,
                status="skipped",
                indexed_count=0,
                skipped_count=len(embeddings),
                warnings=["no_semantic_embeddings_to_index"],
                metadata={"local_only": True, "url": self.url},
            )
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models
        except Exception as error:  # noqa: BLE001 - optional dependency failure.
            return VectorStoreUpsertResult(
                provider=self.provider_name,
                collection=self.collection,
                status="failed",
                indexed_count=0,
                skipped_count=len(embedded_rows),
                warnings=[f"qdrant_client_unavailable:{error.__class__.__name__}"],
                metadata={"local_only": True, "url": self.url},
            )

        chunk_by_id = {chunk.get("chunk_id"): chunk for chunk in chunks}
        vector_size = len(embedded_rows[0]["embedding"])
        try:
            client = QdrantClient(url=self.url)
            if not client.collection_exists(collection_name=self.collection):
                client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
                )
            points = [
                models.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, str(row.get("chunk_id")))),
                    vector=row["embedding"],
                    payload={**chunk_by_id.get(row.get("chunk_id"), {}), "embedding_model": row.get("embedding_model")},
                )
                for row in embedded_rows
            ]
            client.upsert(collection_name=self.collection, points=points)
        except Exception as error:  # noqa: BLE001 - local service may be unavailable.
            return VectorStoreUpsertResult(
                provider=self.provider_name,
                collection=self.collection,
                status="failed",
                indexed_count=0,
                skipped_count=len(embedded_rows),
                warnings=[f"qdrant_upsert_failed:{error.__class__.__name__}"],
                metadata={"local_only": True, "url": self.url},
            )
        return VectorStoreUpsertResult(
            provider=self.provider_name,
            collection=self.collection,
            status="indexed",
            indexed_count=len(points),
            skipped_count=len(embeddings) - len(points),
            warnings=[],
            metadata={"local_only": True, "url": self.url, "vector_size": vector_size},
        )
