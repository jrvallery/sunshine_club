"""Base contracts for semantic-result reranking providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class RerankProviderAttempt:
    provider: str
    model: str
    status: str
    query_count: int
    input_count: int
    output_count: int
    warnings: list[str]
    metadata: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


class RerankProvider(Protocol):
    provider_name: str

    def dependency_status(self) -> dict[str, Any]:
        """Return reranking provider health."""

    def rerank(self, *, query_text: str, documents: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], RerankProviderAttempt]:
        """Rerank semantic retrieval candidates."""
