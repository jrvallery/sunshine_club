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

    def __init__(self, *, url: str | None = None, collection: str | None = None, timeout_seconds: float | None = None) -> None:
        self.url = (url or os.environ.get("SUNSHINE_QDRANT_URL") or "http://127.0.0.1:6333").rstrip("/")
        self.collection = collection or os.environ.get("SUNSHINE_QDRANT_COLLECTION") or "sunshine_chunks"
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else float(os.environ.get("SUNSHINE_QDRANT_TIMEOUT_SECONDS", "3"))

    def dependency_status(self) -> dict[str, Any]:
        try:
            from qdrant_client import QdrantClient
        except Exception as error:  # noqa: BLE001 - optional dependency probe.
            return {
                "provider": self.provider_name,
                "available": False,
                "client_available": False,
                "server_available": False,
                "collection_exists": False,
                "provisioned": False,
                "local_only": True,
                "url": self.url,
                "collection": self.collection,
                "missing": ["qdrant-client"],
                "error": error.__class__.__name__,
            }
        status: dict[str, Any] = {
            "provider": self.provider_name,
            "available": False,
            "client_available": True,
            "server_available": False,
            "collection_exists": False,
            "provisioned": False,
            "local_only": True,
            "url": self.url,
            "collection": self.collection,
            "expected_vector_size": _optional_positive_int(os.environ.get("SUNSHINE_EMBEDDING_DIMENSIONS")),
        }
        try:
            client = _qdrant_client(QdrantClient, url=self.url, timeout_seconds=self.timeout_seconds)
            collection_exists = bool(client.collection_exists(collection_name=self.collection))
            status.update(
                {
                    "available": True,
                    "server_available": True,
                    "collection_exists": collection_exists,
                    "provisioned": collection_exists,
                }
            )
            if collection_exists:
                status["collection_info"] = _collection_summary(client, self.collection) | {"name": self.collection}
        except Exception as error:  # noqa: BLE001 - local service may be down.
            status.update({"error": error.__class__.__name__, "server_status": "unreachable"})
        return status

    def upsert_embeddings(self, chunks: list[dict[str, Any]], embeddings: list[dict[str, Any]]) -> VectorStoreUpsertResult:
        embedded_rows = [row for row in embeddings if row.get("embedding_status") == "embedded" and isinstance(row.get("embedding"), list)]
        if not embedded_rows:
            return VectorStoreUpsertResult(
                provider=self.provider_name,
                collection=self.collection,
                status="skipped",
                indexed_count=0,
                skipped_count=len(embeddings),
                indexed_chunk_ids=[],
                skipped_chunk_ids=[str(row.get("chunk_id")) for row in embeddings if row.get("chunk_id")],
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
                indexed_chunk_ids=[],
                skipped_chunk_ids=[str(row.get("chunk_id")) for row in embedded_rows if row.get("chunk_id")],
                warnings=[f"qdrant_client_unavailable:{error.__class__.__name__}"],
                metadata={"local_only": True, "url": self.url},
            )

        chunk_by_id = {chunk.get("chunk_id"): chunk for chunk in chunks}
        vector_size = len(embedded_rows[0]["embedding"])
        indexed_chunk_ids = [str(row.get("chunk_id")) for row in embedded_rows if row.get("chunk_id")]
        indexed_chunk_id_set = set(indexed_chunk_ids)
        try:
            client = _qdrant_client(QdrantClient, url=self.url, timeout_seconds=self.timeout_seconds)
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
                indexed_chunk_ids=[],
                skipped_chunk_ids=indexed_chunk_ids,
                warnings=[f"qdrant_upsert_failed:{error.__class__.__name__}"],
                metadata={"local_only": True, "url": self.url},
            )
        return VectorStoreUpsertResult(
            provider=self.provider_name,
            collection=self.collection,
            status="indexed",
            indexed_count=len(points),
            skipped_count=len(embeddings) - len(points),
            indexed_chunk_ids=indexed_chunk_ids,
            skipped_chunk_ids=[
                str(row.get("chunk_id"))
                for row in embeddings
                if row.get("chunk_id") and str(row.get("chunk_id")) not in indexed_chunk_id_set
            ],
            warnings=[],
            metadata={
                "local_only": True,
                "url": self.url,
                "vector_size": vector_size,
                "point_count": len(points),
            },
        )


def _qdrant_client(client_class: Any, *, url: str, timeout_seconds: float) -> Any:
    try:
        return client_class(url=url, timeout=timeout_seconds)
    except TypeError:
        return client_class(url=url)


def _collection_summary(client: Any, collection_name: str) -> dict[str, Any]:
    try:
        collection = client.get_collection(collection_name=collection_name)
    except Exception:  # noqa: BLE001 - summary is best-effort readiness metadata.
        return {}
    points_count = getattr(collection, "points_count", None)
    vectors_count = getattr(collection, "vectors_count", None)
    config = getattr(collection, "config", None)
    vector_size = _vector_size_from_config(config)
    return {
        "points_count": points_count,
        "vectors_count": vectors_count,
        "vector_size": vector_size,
    }


def _vector_size_from_config(config: Any) -> int | None:
    params = getattr(config, "params", None)
    vectors = getattr(params, "vectors", None)
    size = getattr(vectors, "size", None)
    if isinstance(size, int):
        return size
    if isinstance(vectors, dict):
        first = next(iter(vectors.values()), None)
        value = getattr(first, "size", None)
        return value if isinstance(value, int) else None
    return None


def _optional_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
