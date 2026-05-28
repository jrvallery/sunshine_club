"""Qdrant semantic retrieval provider."""

from __future__ import annotations

import os
from typing import Any

from sunshine_extraction.embeddings import EmbeddingProvider
from sunshine_extraction.providers.retrieval.base import SemanticRetrievalProviderAttempt


class QdrantSemanticRetrievalProvider:
    provider_name = "qdrant"

    def __init__(self, *, embedding_provider: EmbeddingProvider | None = None, url: str | None = None, collection: str | None = None) -> None:
        self.embedding_provider = embedding_provider
        self.url = (url or os.environ.get("SUNSHINE_QDRANT_URL") or "http://127.0.0.1:6333").rstrip("/")
        self.collection = collection or os.environ.get("SUNSHINE_QDRANT_COLLECTION") or "sunshine_chunks"

    def dependency_status(self) -> dict[str, Any]:
        try:
            import qdrant_client  # noqa: F401
        except Exception as error:  # noqa: BLE001
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

    def retrieve(
        self,
        *,
        index_path: str | None,
        query_text: str,
        limit: int,
    ) -> tuple[list[dict[str, Any]], SemanticRetrievalProviderAttempt]:
        del index_path
        if self.embedding_provider is None:
            return [], SemanticRetrievalProviderAttempt(
                provider=self.provider_name,
                status="skipped",
                index_path=self.collection,
                query_count=0,
                result_count=0,
                warnings=["qdrant_embedding_provider_missing"],
                metadata={"local_only": True, "url": self.url, "collection": self.collection, "limit": limit},
            )
        try:
            from qdrant_client import QdrantClient
        except Exception as error:  # noqa: BLE001
            return [], SemanticRetrievalProviderAttempt(
                provider=self.provider_name,
                status="failed",
                index_path=self.collection,
                query_count=0,
                result_count=0,
                warnings=[f"qdrant_client_unavailable:{error.__class__.__name__}"],
                metadata={"local_only": True, "url": self.url, "collection": self.collection, "limit": limit},
            )
        try:
            query_vector = self.embedding_provider.embed([query_text])[0]
            client = QdrantClient(url=self.url)
            points = _search_points(client, collection=self.collection, query_vector=query_vector, limit=limit)
        except Exception as error:  # noqa: BLE001
            return [], SemanticRetrievalProviderAttempt(
                provider=self.provider_name,
                status="failed",
                index_path=self.collection,
                query_count=1,
                result_count=0,
                warnings=[f"qdrant_semantic_retrieval_failed:{error.__class__.__name__}"],
                metadata={"error": f"{error.__class__.__name__}: {error}", "local_only": True, "url": self.url, "collection": self.collection, "limit": limit},
            )
        examples = [_point_to_example(point) for point in points]
        return examples, SemanticRetrievalProviderAttempt(
            provider=self.provider_name,
            status="retrieved",
            index_path=self.collection,
            query_count=1,
            result_count=len(examples),
            warnings=[],
            metadata={"local_only": True, "url": self.url, "collection": self.collection, "limit": limit},
        )


def _search_points(client: Any, *, collection: str, query_vector: list[float], limit: int) -> list[Any]:
    if hasattr(client, "search"):
        return list(client.search(collection_name=collection, query_vector=query_vector, limit=limit, with_payload=True))
    result = client.query_points(collection_name=collection, query=query_vector, limit=limit, with_payload=True)
    return list(getattr(result, "points", result))


def _point_to_example(point: Any) -> dict[str, Any]:
    payload = getattr(point, "payload", None) or {}
    score = getattr(point, "score", None)
    if isinstance(point, dict):
        payload = point.get("payload") or {}
        score = point.get("score")
    return {
        **payload,
        "score": score,
        "retrieval_provider": "qdrant",
    }


__all__ = ["QdrantSemanticRetrievalProvider"]
