"""Qdrant semantic retrieval provider boundary.

Indexing into Qdrant exists today. Query-time reviewed-example retrieval is
reserved behind this provider so the graph can swap from SQLite golden examples
to Qdrant without changing node shape.
"""

from __future__ import annotations

import os
from typing import Any

from sunshine_extraction.providers.retrieval.base import SemanticRetrievalProviderAttempt


class QdrantSemanticRetrievalProvider:
    provider_name = "qdrant"

    def __init__(self, *, url: str | None = None, collection: str | None = None) -> None:
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
        return [], SemanticRetrievalProviderAttempt(
            provider=self.provider_name,
            status="skipped",
            index_path=self.collection,
            query_count=0,
            result_count=0,
            warnings=["qdrant_semantic_retrieval_not_enabled"],
            metadata={"local_only": True, "url": self.url, "collection": self.collection, "limit": limit},
        )


__all__ = ["QdrantSemanticRetrievalProvider"]
