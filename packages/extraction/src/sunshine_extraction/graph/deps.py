"""Dependency resolution for graph providers and optional indexes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sunshine_extraction.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingProvider,
    PlaceholderEmbeddingProvider,
    provider_from_env,
)
from sunshine_extraction.graph.state import DocumentPipelineDeps
from sunshine_extraction.providers.chunking import ChunkingProvider, CurrentChunkingProvider
from sunshine_extraction.providers.embeddings import ChunkEmbeddingProvider, CurrentChunkEmbeddingProvider
from sunshine_extraction.providers.extraction import ExtractionProvider, extraction_provider_from_env
from sunshine_extraction.providers.llm import CurrentLLMTagInspectionProvider, LLMTagInspectionProvider
from sunshine_extraction.providers.observability import ObservabilityProvider, observability_provider_from_env
from sunshine_extraction.providers.reranking import CortexRerankProvider, RerankProvider
from sunshine_extraction.providers.retrieval import CurrentSemanticRetrievalProvider, QdrantSemanticRetrievalProvider, SemanticRetrievalProvider
from sunshine_extraction.providers.vectorstores import NoopVectorStoreProvider, QdrantVectorStoreProvider, VectorStoreProvider
from sunshine_extraction.services.cache import SQLiteModelCallCache, model_call_cache_from_env
from sunshine_extraction.services.extraction import OcrExecutor, ocr_executor_from_env
from sunshine_extraction.services.imports import RunResultsImporter, run_results_importer_from_env
from sunshine_extraction.services.provider_policy import assert_production_local_only_environment
from sunshine_extraction.services.tagging import LLMTagInspector, llm_tag_inspector_from_env
from sunshine_extraction.services.vector_policy import vector_store_policy_from_env

SEMANTIC_INDEX_FROM_ENV = object()


def _resolve_deps(
    *,
    embedding_provider: EmbeddingProvider | None = None,
    extraction_provider: ExtractionProvider | None = None,
    chunking_provider: ChunkingProvider | None = None,
    chunk_embedding_provider: ChunkEmbeddingProvider | None = None,
    vector_store: VectorStoreProvider | None = None,
    semantic_retrieval_provider: SemanticRetrievalProvider | None = None,
    rerank_provider: RerankProvider | None = None,
    llm_tag_inspection_provider: LLMTagInspectionProvider | None = None,
    observability_provider: ObservabilityProvider | None = None,
    embedding_failure_mode: str | None = None,
    llm_tag_inspector: LLMTagInspector | None = None,
    ocr_executor: OcrExecutor | None = None,
    run_results_importer: RunResultsImporter | None = None,
    model_call_cache: SQLiteModelCallCache | None = None,
    semantic_index_path: str | Path | None | object = SEMANTIC_INDEX_FROM_ENV,
    semantic_retrieval_filter: dict[str, Any] | None = None,
) -> DocumentPipelineDeps:
    assert_production_local_only_environment()
    if embedding_provider is None:
        try:
            embedding_provider = provider_from_env()
        except EmbeddingConfigurationError:
            embedding_provider = PlaceholderEmbeddingProvider()
    active_llm_tag_inspector = llm_tag_inspector or llm_tag_inspector_from_env()
    active_model_call_cache = model_call_cache if model_call_cache is not None else model_call_cache_from_env()
    deps: DocumentPipelineDeps = {
        "extraction_provider": extraction_provider or extraction_provider_from_env(),
        "chunking_provider": chunking_provider or CurrentChunkingProvider(),
        "chunk_embedding_provider": chunk_embedding_provider or CurrentChunkEmbeddingProvider(embedding_provider, cache=active_model_call_cache),
        "vector_store": vector_store or _vector_store_from_env(),
        "semantic_retrieval_provider": semantic_retrieval_provider or _semantic_retrieval_provider_from_env(embedding_provider),
        "rerank_provider": rerank_provider if rerank_provider is not None else _rerank_provider_from_env(cache=active_model_call_cache),
        "llm_tag_inspection_provider": llm_tag_inspection_provider or CurrentLLMTagInspectionProvider(active_llm_tag_inspector, cache=active_model_call_cache),
        "embedding_provider": embedding_provider,
        "embedding_failure_mode": _embedding_failure_mode(embedding_failure_mode),
        "llm_tag_inspector": active_llm_tag_inspector,
        "ocr_executor": ocr_executor or ocr_executor_from_env(),
        "run_results_importer": run_results_importer or run_results_importer_from_env(),
        "observability_provider": observability_provider or observability_provider_from_env(),
        "model_call_cache": active_model_call_cache,
        "semantic_index_path": _resolve_semantic_index_path(semantic_index_path),
    }
    active_retrieval_filter = semantic_retrieval_filter if semantic_retrieval_filter is not None else _semantic_retrieval_filter_from_env()
    if active_retrieval_filter:
        deps["semantic_retrieval_filter"] = active_retrieval_filter
    return deps


def _embedding_failure_mode(configured: str | None) -> str:
    mode = (configured or os.environ.get("SUNSHINE_EMBEDDING_FAILURE_MODE") or "fallback").strip().lower()
    if mode in {"review", "fail_closed", "fail-closed", "strict"}:
        return "review"
    return "fallback"


def _vector_store_from_env() -> VectorStoreProvider:
    provider_name = vector_store_policy_from_env()["provider"]
    if provider_name == "noop":
        return NoopVectorStoreProvider()
    if provider_name == "qdrant":
        return QdrantVectorStoreProvider()
    if provider_name == "sqlite_golden":
        return NoopVectorStoreProvider()
    return NoopVectorStoreProvider()


def _semantic_retrieval_provider_from_env(embedding_provider: EmbeddingProvider) -> SemanticRetrievalProvider:
    provider_name = os.environ.get("SUNSHINE_RETRIEVAL_PROVIDER", "sqlite_semantic_index").strip().lower()
    if provider_name == "qdrant":
        return QdrantSemanticRetrievalProvider(embedding_provider=embedding_provider)
    return CurrentSemanticRetrievalProvider(embedding_provider)


def _rerank_provider_from_env(*, cache: SQLiteModelCallCache | None = None) -> RerankProvider | None:
    provider_name = os.environ.get("SUNSHINE_RERANK_PROVIDER", "").strip().lower()
    if not provider_name or provider_name in {"disabled", "none", "off"}:
        return None
    if provider_name != "cortex":
        raise ValueError("SUNSHINE_RERANK_PROVIDER must be cortex or disabled")
    from sunshine_extraction.cortex import DEFAULT_CORTEX_RERANK_MODEL
    from sunshine_extraction.config import DEFAULT_CORTEX_BASE_URL

    return CortexRerankProvider(
        api_key=os.environ.get("CORTEX_API_KEY") or os.environ.get("CORTEX_OPENAI_API_KEY", ""),
        base_url=os.environ.get("CORTEX_BASE_URL", DEFAULT_CORTEX_BASE_URL),
        model=os.environ.get("SUNSHINE_RERANK_MODEL", DEFAULT_CORTEX_RERANK_MODEL),
        timeout_seconds=float(os.environ.get("SUNSHINE_RERANK_TIMEOUT_SECONDS", "120")),
        cache=cache,
    )


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


def _semantic_retrieval_filter_from_env() -> dict[str, Any] | None:
    configured = os.environ.get("SUNSHINE_RETRIEVAL_FILTER_JSON", "").strip()
    if not configured:
        return None
    return parse_semantic_retrieval_filter(configured)


def parse_semantic_retrieval_filter(configured: str | dict[str, Any] | None) -> dict[str, Any] | None:
    if configured is None:
        return None
    if isinstance(configured, dict):
        return _clean_retrieval_filter(configured)
    parsed = json.loads(configured)
    if not isinstance(parsed, dict):
        raise ValueError("semantic retrieval filter must be a JSON object")
    return _clean_retrieval_filter(parsed)


def _clean_retrieval_filter(configured: dict[str, Any]) -> dict[str, Any] | None:
    cleaned = {str(key): value for key, value in configured.items() if value is not None and value != ""}
    return cleaned or None
