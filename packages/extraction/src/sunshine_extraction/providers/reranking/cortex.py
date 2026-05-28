"""Cortex reranking provider."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.config import DEFAULT_CORTEX_BASE_URL
from sunshine_extraction.cortex import DEFAULT_CORTEX_RERANK_MODEL, CortexClient
from sunshine_extraction.providers.extraction.ocr_common import cortex_root_base_url
from sunshine_extraction.providers.reranking.base import RerankProviderAttempt


class CortexRerankProvider:
    provider_name = "cortex"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_CORTEX_BASE_URL,
        model: str = DEFAULT_CORTEX_RERANK_MODEL,
        timeout_seconds: float = 120,
    ) -> None:
        self.api_key = api_key
        self.base_url = cortex_root_base_url(base_url)
        self.model = model
        self.timeout_seconds = timeout_seconds

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
        return reranked, RerankProviderAttempt(
            provider=self.provider_name,
            model=self.model,
            status="reranked",
            query_count=1,
            input_count=len(documents),
            output_count=len(reranked),
            warnings=[],
            metadata={"local_only": True, "base_url": self.base_url},
        )


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


__all__ = ["CortexRerankProvider"]
