"""Local semantic search services for citation-first dashboard retrieval."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.embeddings import provider_from_env
from sunshine_extraction.providers.retrieval import QdrantSemanticRetrievalProvider
from sunshine_extraction.services.env import load_pipeline_env


def search_semantic_content(
    *,
    query: str,
    limit: int = 10,
    collection: str | None = None,
    metadata_filter: dict[str, Any] | None = None,
    retrieval_provider: QdrantSemanticRetrievalProvider | None = None,
) -> dict[str, Any]:
    """Run local Qdrant semantic search and return citation-first matches."""

    query_text = query.strip()
    if not query_text:
        raise ValueError("query is required")
    load_pipeline_env()
    active_provider = retrieval_provider or QdrantSemanticRetrievalProvider(
        embedding_provider=provider_from_env(),
        collection=collection,
    )
    matches, attempt = active_provider.retrieve(
        index_path=None,
        query_text=query_text,
        limit=max(1, min(int(limit), 50)),
        metadata_filter=_clean_metadata_filter(metadata_filter),
    )
    return {
        "ok": attempt.status == "retrieved",
        "query": query_text,
        "local_only": True,
        "provider": attempt.provider,
        "collection": attempt.index_path,
        "status": attempt.status,
        "warnings": attempt.warnings,
        "metadata_filter": _clean_metadata_filter(metadata_filter),
        "attempt": attempt.as_row(),
        "matches": [_semantic_search_match(row) for row in matches],
    }


def _clean_metadata_filter(metadata_filter: dict[str, Any] | None) -> dict[str, Any]:
    return {str(key): value for key, value in (metadata_filter or {}).items() if value not in (None, "")}


def _semantic_search_match(row: dict[str, Any]) -> dict[str, Any]:
    citation = row.get("citation") if isinstance(row.get("citation"), dict) else {}
    return {
        "score": row.get("score"),
        "source_path": citation.get("source_path") or row.get("source_path"),
        "relative_path": citation.get("relative_path") or row.get("relative_path"),
        "sample_path": citation.get("sample_path") or row.get("sample_path"),
        "chunk_id": citation.get("chunk_id") or row.get("chunk_id"),
        "chunk_index": citation.get("chunk_index") or row.get("chunk_index"),
        "chunk_kind": citation.get("chunk_kind") or row.get("chunk_kind"),
        "segment_id": citation.get("segment_id") or row.get("segment_id"),
        "page_start": citation.get("page_start"),
        "page_end": citation.get("page_end"),
        "text_snippet": citation.get("text_snippet") or row.get("text_snippet") or row.get("content"),
        "retrieval_explanation": row.get("retrieval_explanation"),
        "citation": citation,
        "raw": row,
    }


__all__ = ["search_semantic_content"]
