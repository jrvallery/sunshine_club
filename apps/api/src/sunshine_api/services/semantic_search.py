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
        "run_key": _row_value(row, citation, "run_key"),
        "content_class": _row_value(row, citation, "content_class"),
        "primary_tag": _row_value(row, citation, "primary_tag"),
        "route_status": _row_value(row, citation, "route_status"),
        "review_status": _row_value(row, citation, "review_status"),
        "chunk_id": _row_value(row, citation, "chunk_id"),
        "chunk_index": _row_value(row, citation, "chunk_index"),
        "chunk_kind": _row_value(row, citation, "chunk_kind"),
        "segment_id": _row_value(row, citation, "segment_id"),
        "segment_type": _row_value(row, citation, "segment_type"),
        "segment_title": _row_value(row, citation, "segment_title"),
        "page_start": citation.get("page_start"),
        "page_end": citation.get("page_end"),
        "text_snippet": citation.get("text_snippet") or row.get("text_snippet") or row.get("content"),
        "retrieval_explanation": row.get("retrieval_explanation"),
        "citation": citation,
        "raw": row,
    }


def _row_value(row: dict[str, Any], citation: dict[str, Any], key: str) -> Any:
    value = citation.get(key)
    if value is not None:
        return value
    value = row.get(key)
    if value is not None:
        return value
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        return metadata.get(key)
    return None


__all__ = ["search_semantic_content"]
