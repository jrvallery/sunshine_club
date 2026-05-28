"""Dependency resolution for graph providers and optional indexes."""

from __future__ import annotations

import os
from pathlib import Path

from sunshine_extraction.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingProvider,
    PlaceholderEmbeddingProvider,
    provider_from_env,
)
from sunshine_extraction.graph.state import DocumentPipelineDeps
from sunshine_extraction.providers.extraction import CurrentExtractionProvider, ExtractionProvider
from sunshine_extraction.providers.vectorstores import NoopVectorStoreProvider, QdrantVectorStoreProvider, VectorStoreProvider
from sunshine_extraction.services.extraction import OcrExecutor, ocr_executor_from_env
from sunshine_extraction.services.tagging import LLMTagInspector, llm_tag_inspector_from_env

SEMANTIC_INDEX_FROM_ENV = object()


def _resolve_deps(
    *,
    embedding_provider: EmbeddingProvider | None = None,
    extraction_provider: ExtractionProvider | None = None,
    vector_store: VectorStoreProvider | None = None,
    embedding_failure_mode: str | None = None,
    llm_tag_inspector: LLMTagInspector | None = None,
    ocr_executor: OcrExecutor | None = None,
    semantic_index_path: str | Path | None | object = SEMANTIC_INDEX_FROM_ENV,
) -> DocumentPipelineDeps:
    if embedding_provider is None:
        try:
            embedding_provider = provider_from_env()
        except EmbeddingConfigurationError:
            embedding_provider = PlaceholderEmbeddingProvider()
    return {
        "extraction_provider": extraction_provider or CurrentExtractionProvider(),
        "vector_store": vector_store or _vector_store_from_env(),
        "embedding_provider": embedding_provider,
        "embedding_failure_mode": _embedding_failure_mode(embedding_failure_mode),
        "llm_tag_inspector": llm_tag_inspector or llm_tag_inspector_from_env(),
        "ocr_executor": ocr_executor or ocr_executor_from_env(),
        "semantic_index_path": _resolve_semantic_index_path(semantic_index_path),
    }


def _embedding_failure_mode(configured: str | None) -> str:
    mode = (configured or os.environ.get("SUNSHINE_EMBEDDING_FAILURE_MODE") or "fallback").strip().lower()
    if mode in {"review", "fail_closed", "fail-closed", "strict"}:
        return "review"
    return "fallback"


def _vector_store_from_env() -> VectorStoreProvider:
    provider_name = os.environ.get("SUNSHINE_VECTOR_STORE", "noop").strip().lower()
    if provider_name in {"", "none", "disabled", "noop"}:
        return NoopVectorStoreProvider()
    if provider_name == "qdrant":
        return QdrantVectorStoreProvider()
    return NoopVectorStoreProvider()


def _semantic_index_path_from_env() -> str | None:
    configured = os.environ.get("SUNSHINE_SEMANTIC_INDEX_PATH", "").strip()
    if not configured:
        return None
    return configured


def _resolve_semantic_index_path(semantic_index_path: str | Path | None | object) -> str | None:
    if semantic_index_path is SEMANTIC_INDEX_FROM_ENV:
        return _semantic_index_path_from_env()
    if semantic_index_path is None:
        return None
    return str(semantic_index_path)
