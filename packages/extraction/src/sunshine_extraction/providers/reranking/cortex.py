"""Cortex reranking provider."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.config import DEFAULT_CORTEX_BASE_URL
from sunshine_extraction.cortex import DEFAULT_CORTEX_RERANK_MODEL, CortexClient
from sunshine_extraction.providers.extraction.ocr_common import cortex_root_base_url
from sunshine_extraction.providers.reranking.base import RerankProviderAttempt
from sunshine_extraction.providers.reranking.cache import rerank_cache_key
from sunshine_extraction.services.cache import SQLiteModelCallCache


class CortexRerankProvider:
    provider_name = "cortex"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_CORTEX_BASE_URL,
        model: str = DEFAULT_CORTEX_RERANK_MODEL,
        timeout_seconds: float = 120,
        cache: SQLiteModelCallCache | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = cortex_root_base_url(base_url)
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.cache = cache

    def dependency_status(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model": self.model,
            "base_url": self.base_url,
            "available": bool(self.api_key),
            "local_only": True,
            "missing": [] if self.api_key else ["api_key"],
        }

    def rerank(self, *, query_text: str, documents: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], RerankProviderAttempt]:
        if not documents:
            return [], RerankProviderAttempt(
                provider=self.provider_name,
                model=self.model,
                status="skipped",
                query_count=0,
                input_count=0,
                output_count=0,
                warnings=["no_documents_to_rerank"],
                metadata={"local_only": True},
            )
        cache_key = rerank_cache_key(
            query_text=query_text,
            documents=documents,
            provider=self.provider_name,
            model=self.model,
            limit=limit,
        )
        if self.cache is not None:
            cached = self.cache.get_json("reranking", cache_key)
            if cached:
                self.cache.record_hit("reranking", cache_key)
                return _cached_rerank(cached, provider=self.provider_name, model=self.model)
        if not self.api_key:
            return documents[:limit], RerankProviderAttempt(
                provider=self.provider_name,
                model=self.model,
                status="skipped",
                query_count=0,
                input_count=len(documents),
                output_count=min(limit, len(documents)),
                warnings=["cortex_rerank_api_key_missing"],
                metadata={"local_only": True, "base_url": self.base_url},
            )
        try:
            payload = CortexClient(base_url=self.base_url, api_key=self.api_key, timeout_seconds=self.timeout_seconds).rerank(
                query=query_text,
                documents=documents,
                model=self.model,
                top_n=limit,
                return_documents=True,
            )
        except Exception as error:  # noqa: BLE001
            return documents[:limit], RerankProviderAttempt(
                provider=self.provider_name,
                model=self.model,
                status="failed",
                query_count=1,
                input_count=len(documents),
                output_count=min(limit, len(documents)),
                warnings=[f"cortex_rerank_failed:{type(error).__name__}"],
                metadata={"local_only": True, "base_url": self.base_url},
            )
        reranked = _reranked_documents(payload, documents, limit)
        attempt = RerankProviderAttempt(
            provider=self.provider_name,
            model=self.model,
            status="reranked",
            query_count=1,
            input_count=len(documents),
            output_count=len(reranked),
            warnings=[],
            metadata={"local_only": True, "base_url": self.base_url},
        )
        if self.cache is not None:
            self.cache.set_json(
                "reranking",
                cache_key,
                {
                    "documents": reranked,
                    "attempt": attempt.as_row(),
                },
            )
        return reranked, attempt


def _reranked_documents(payload: dict[str, Any], fallback: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    results = payload.get("results") or payload.get("data") or payload.get("documents")
    if not isinstance(results, list):
        return fallback[:limit]
    reranked: list[dict[str, Any]] = []
    for row in results[:limit]:
        if not isinstance(row, dict):
            continue
        document = row.get("document") if isinstance(row.get("document"), dict) else row
        score = row.get("relevance_score") or row.get("score")
        merged = dict(document)
        if isinstance(score, int | float):
            merged["rerank_score"] = float(score)
        reranked.append(merged)
    return reranked or fallback[:limit]


def _cached_rerank(payload: dict[str, Any], *, provider: str, model: str) -> tuple[list[dict[str, Any]], RerankProviderAttempt]:
    documents = payload.get("documents")
    if not isinstance(documents, list):
        documents = []
    attempt_payload = dict(payload.get("attempt") or {})
    metadata = dict(attempt_payload.get("metadata") or {})
    metadata.update({"cache_hit": True, "local_only": True})
    return [dict(document) for document in documents if isinstance(document, dict)], RerankProviderAttempt(
        provider=str(attempt_payload.get("provider") or provider),
        model=str(attempt_payload.get("model") or model),
        status=str(attempt_payload.get("status") or "reranked"),
        query_count=0,
        input_count=int(attempt_payload.get("input_count") or len(documents)),
        output_count=int(attempt_payload.get("output_count") or len(documents)),
        warnings=list(attempt_payload.get("warnings") or []),
        metadata=metadata,
    )


__all__ = ["CortexRerankProvider"]
