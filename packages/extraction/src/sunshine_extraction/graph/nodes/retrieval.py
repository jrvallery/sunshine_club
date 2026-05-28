"""Semantic example retrieval node."""

from __future__ import annotations

import time
from typing import Any

from sunshine_extraction.embeddings import PlaceholderEmbeddingProvider
from sunshine_extraction.graph.model_usage import _cost_basis, _embedding_model_usage_row, _model_usage_row
from sunshine_extraction.graph.node_utils import _empty_extraction
from sunshine_extraction.graph.state import DocumentPipelineDeps, DocumentPipelineState
from sunshine_extraction.providers.reranking import RerankProviderAttempt


def _retrieve_labeled_examples_node(state: DocumentPipelineState, deps: DocumentPipelineDeps) -> dict[str, Any]:
    index_path = deps.get("semantic_index_path")
    extraction = state.get("extraction_result") or _empty_extraction(state)
    query_text = _semantic_query_text(state, extraction)
    started = time.monotonic()
    examples, retrieval_attempt = deps["semantic_retrieval_provider"].retrieve(
        index_path=index_path,
        query_text=query_text,
        limit=5,
        metadata_filter=deps.get("semantic_retrieval_filter"),
    )
    warnings = [*state.get("warnings", []), *retrieval_attempt.warnings]
    if retrieval_attempt.status == "skipped":
        provider_name = _embedding_provider_name(deps["embedding_provider"])
        usage_row = _model_usage_row(
            state,
            node="retrieve_labeled_examples",
            purpose="semantic_retrieval_embedding",
            provider=provider_name,
            model=str(getattr(deps["embedding_provider"], "model", "unknown")),
            status="skipped",
            runtime_ms=0,
            cost_basis=_cost_basis(provider_name),
            metadata={
                "call_count": 0,
                "reason": "semantic_index_missing",
                "semantic_index_path": str(index_path) if index_path else None,
                "cost_estimate": "unavailable",
            },
        )
        return {
            "semantic_examples": [],
            "retrieval_result": retrieval_attempt.as_row(),
            "warnings": warnings,
            "model_usage": [*state.get("model_usage", []), usage_row],
        }
    if retrieval_attempt.status == "failed":
        usage_row = _embedding_model_usage_row(
            state,
            deps["embedding_provider"],
            node="retrieve_labeled_examples",
            purpose="semantic_retrieval_embedding",
            status="failed",
            call_count=retrieval_attempt.query_count,
            started=started,
            error=str(retrieval_attempt.metadata.get("error") or ";".join(retrieval_attempt.warnings) or ""),
        )
        return {
            "semantic_examples": [],
            "retrieval_result": retrieval_attempt.as_row(),
            "warnings": warnings,
            "model_usage": [*state.get("model_usage", []), usage_row] if usage_row else state.get("model_usage", []),
        }
    usage_row = _embedding_model_usage_row(
        state,
        deps["embedding_provider"],
        node="retrieve_labeled_examples",
        purpose="semantic_retrieval_embedding",
        status="placeholder" if isinstance(deps["embedding_provider"], PlaceholderEmbeddingProvider) else "ok",
        call_count=1,
        started=started,
    )
    examples, rerank_attempt, rerank_usage = _maybe_rerank_examples(
        state,
        deps,
        query_text=query_text,
        examples=examples,
        limit=5,
    )
    retrieval_row = retrieval_attempt.as_row()
    if rerank_attempt is not None:
        retrieval_row = {
            **retrieval_row,
            "metadata": {**(retrieval_row.get("metadata") or {}), "rerank": rerank_attempt.as_row()},
        }
    return {
        "semantic_examples": examples,
        "retrieval_result": retrieval_row,
        "warnings": warnings,
        "model_usage": [
            *state.get("model_usage", []),
            *([usage_row] if usage_row else []),
            *([rerank_usage] if rerank_usage else []),
        ],
    }


def _maybe_rerank_examples(
    state: DocumentPipelineState,
    deps: DocumentPipelineDeps,
    *,
    query_text: str,
    examples: list[dict[str, Any]],
    limit: int,
) -> tuple[list[dict[str, Any]], RerankProviderAttempt | None, dict[str, Any] | None]:
    reranker = deps.get("rerank_provider")
    if reranker is None:
        return examples, None, None
    started = time.monotonic()
    reranked_examples, attempt = reranker.rerank(query_text=query_text, documents=examples, limit=limit)
    usage = _model_usage_row(
        state,
        node="retrieve_labeled_examples",
        purpose="semantic_example_rerank",
        provider=attempt.provider,
        model=attempt.model,
        host=_provider_host_from_attempt(attempt),
        status="ok" if attempt.status == "reranked" else attempt.status,
        runtime_ms=round((time.monotonic() - started) * 1000),
        error=";".join(attempt.warnings) or None,
        cost_basis=_cost_basis(attempt.provider),
        metadata={
            **attempt.metadata,
            "call_count": attempt.query_count,
            "input_count": attempt.input_count,
            "output_count": attempt.output_count,
            "cost_estimate": "unavailable",
        },
    )
    return reranked_examples, attempt, usage


def _provider_host_from_attempt(attempt: RerankProviderAttempt) -> str | None:
    base_url = attempt.metadata.get("base_url")
    if isinstance(base_url, str) and base_url:
        from sunshine_extraction.graph.model_usage import _host_from_url

        return _host_from_url(base_url)
    return "local" if attempt.metadata.get("local_only") else None


def _semantic_query_text(state: DocumentPipelineState, extraction: Any) -> str:
    return "\n".join(
        [
            f"relative_path: {state.get('relative_path', '')}",
            f"filename: {state.get('filename', '')}",
            f"content_class: {state.get('content_class', {}).get('final_class', '')}",
            f"document_subtype: {state.get('extraction_plan', {}).get('document_subtype', '')}",
            f"text: {extraction.text[:2500]}",
        ]
    )


def _embedding_provider_name(provider: Any) -> str:
    return str(getattr(provider, "provider_name", "") or provider.__class__.__name__.replace("EmbeddingProvider", "").lower() or "embedding")
