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
        metadata_filter: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], SemanticRetrievalProviderAttempt]:
        del index_path
        metadata = _attempt_metadata(self.url, self.collection, limit, metadata_filter)
        if self.embedding_provider is None:
            return [], SemanticRetrievalProviderAttempt(
                provider=self.provider_name,
                status="skipped",
                index_path=self.collection,
                query_count=0,
                result_count=0,
                warnings=["qdrant_embedding_provider_missing"],
                metadata=metadata,
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
                metadata=metadata,
            )
        try:
            query_vector = self.embedding_provider.embed([query_text])[0]
            client = QdrantClient(url=self.url)
            points = _search_points(
                client,
                collection=self.collection,
                query_vector=query_vector,
                limit=limit,
                metadata_filter=metadata_filter,
            )
        except Exception as error:  # noqa: BLE001
            return [], SemanticRetrievalProviderAttempt(
                provider=self.provider_name,
                status="failed",
                index_path=self.collection,
                query_count=1,
                result_count=0,
                warnings=[f"qdrant_semantic_retrieval_failed:{error.__class__.__name__}"],
                metadata={**metadata, "error": f"{error.__class__.__name__}: {error}"},
            )
        examples = [_point_to_example(point) for point in points]
        return examples, SemanticRetrievalProviderAttempt(
            provider=self.provider_name,
            status="retrieved",
            index_path=self.collection,
            query_count=1,
            result_count=len(examples),
            warnings=[],
            metadata=metadata,
        )


def _attempt_metadata(url: str, collection: str, limit: int, metadata_filter: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "local_only": True,
        "url": url,
        "collection": collection,
        "limit": limit,
        "metadata_filter": metadata_filter or {},
    }


def _search_points(
    client: Any,
    *,
    collection: str,
    query_vector: list[float],
    limit: int,
    metadata_filter: dict[str, Any] | None = None,
) -> list[Any]:
    query_filter = _qdrant_filter(metadata_filter)
    if hasattr(client, "search"):
        return list(client.search(collection_name=collection, query_vector=query_vector, limit=limit, with_payload=True, query_filter=query_filter))
    result = client.query_points(collection_name=collection, query=query_vector, limit=limit, with_payload=True, query_filter=query_filter)
    return list(getattr(result, "points", result))


def _qdrant_filter(metadata_filter: dict[str, Any] | None) -> Any:
    filtered_items = {str(key): value for key, value in (metadata_filter or {}).items() if value is not None}
    if not filtered_items:
        return None
    try:
        from qdrant_client.http import models

        return models.Filter(
            must=[
                models.FieldCondition(key=key, match=models.MatchValue(value=value))
                for key, value in sorted(filtered_items.items())
            ]
        )
    except Exception:  # noqa: BLE001 - tests and lightweight installs may not expose model classes.
        return {
            "must": [
                {"key": key, "match": {"value": value}}
                for key, value in sorted(filtered_items.items())
            ]
        }


def _point_to_example(point: Any) -> dict[str, Any]:
    payload = getattr(point, "payload", None) or {}
    score = getattr(point, "score", None)
    if isinstance(point, dict):
        payload = point.get("payload") or {}
        score = point.get("score")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    citation = _citation_from_payload(payload, metadata, score)
    return {
        **payload,
        "score": score,
        "retrieval_provider": "qdrant",
        "retrieval_explanation": _retrieval_explanation(score, citation),
        "citation": citation,
    }


def _citation_from_payload(payload: dict[str, Any], metadata: dict[str, Any], score: Any) -> dict[str, Any]:
    return {
        "source_path": _payload_value(payload, metadata, "source_path"),
        "relative_path": _payload_value(payload, metadata, "relative_path"),
        "sample_path": _payload_value(payload, metadata, "sample_path"),
        "chunk_id": _payload_value(payload, metadata, "chunk_id"),
        "chunk_index": _payload_value(payload, metadata, "chunk_index"),
        "chunk_kind": _payload_value(payload, metadata, "chunk_kind"),
        "segment_id": _payload_value(payload, metadata, "segment_id"),
        "parent_segment_id": _payload_value(payload, metadata, "parent_segment_id"),
        "page_start": _payload_value(payload, metadata, "page_start"),
        "page_end": _payload_value(payload, metadata, "page_end"),
        "segment_title": _payload_value(payload, metadata, "segment_title"),
        "segment_type": _payload_value(payload, metadata, "segment_type"),
        "score": score,
        "text_snippet": _text_snippet(payload),
    }


def _payload_value(payload: dict[str, Any], metadata: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    if value is not None:
        return value
    return metadata.get(key)


def _text_snippet(payload: dict[str, Any]) -> str | None:
    text = payload.get("text")
    if text is None:
        text = payload.get("content")
    if text is None:
        return None
    normalized = " ".join(str(text).split())
    if len(normalized) <= 240:
        return normalized
    return normalized[:237].rstrip() + "..."


def _retrieval_explanation(score: Any, citation: dict[str, Any]) -> str:
    parts = ["qdrant_vector_match"]
    if score is not None:
        parts.append(f"score:{score}")
    if citation.get("chunk_id"):
        parts.append(f"chunk:{citation['chunk_id']}")
    if citation.get("segment_id"):
        parts.append(f"segment:{citation['segment_id']}")
    page_start = citation.get("page_start")
    page_end = citation.get("page_end")
    if page_start is not None and page_end is not None:
        parts.append(f"pages:{page_start}-{page_end}")
    elif page_start is not None:
        parts.append(f"page:{page_start}")
    return " | ".join(parts)


__all__ = ["QdrantSemanticRetrievalProvider"]
