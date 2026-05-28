"""SQLite semantic-index retrieval provider for golden examples."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sunshine_extraction.embeddings import EmbeddingProvider
from sunshine_extraction.providers.retrieval.base import SemanticRetrievalProviderAttempt
from sunshine_extraction.semantic_index import search_semantic_index


class CurrentSemanticRetrievalProvider:
    provider_name = "sqlite_semantic_index"

    def __init__(self, embedding_provider: EmbeddingProvider) -> None:
        self.embedding_provider = embedding_provider

    def dependency_status(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "available": True,
            "local_only": True,
            "embedding_model": getattr(self.embedding_provider, "model", "unknown"),
        }

    def retrieve(
        self,
        *,
        index_path: str | None,
        query_text: str,
        limit: int,
        metadata_filter: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], SemanticRetrievalProviderAttempt]:
        del metadata_filter
        if not index_path or not Path(index_path).exists():
            return [], SemanticRetrievalProviderAttempt(
                provider=self.provider_name,
                status="skipped",
                index_path=str(index_path) if index_path else None,
                query_count=0,
                result_count=0,
                warnings=["semantic_index_missing"],
                metadata={"reason": "semantic_index_missing", "local_only": True},
            )
        try:
            examples = search_semantic_index(index_path, query_text, embedding_provider=self.embedding_provider, limit=limit)
        except Exception as error:  # noqa: BLE001 - retrieval failure should not block graph routing.
            return [], SemanticRetrievalProviderAttempt(
                provider=self.provider_name,
                status="failed",
                index_path=str(index_path),
                query_count=1,
                result_count=0,
                warnings=[f"semantic_example_retrieval_failed:{type(error).__name__}"],
                metadata={"error": f"{type(error).__name__}: {error}", "local_only": True},
            )
        return examples, SemanticRetrievalProviderAttempt(
            provider=self.provider_name,
            status="retrieved",
            index_path=str(index_path),
            query_count=1,
            result_count=len(examples),
            warnings=[],
            metadata={"limit": limit, "local_only": True},
        )
