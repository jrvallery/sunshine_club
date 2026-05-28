"""Base contracts for semantic example retrieval providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SemanticRetrievalProviderAttempt:
    provider: str
    status: str
    index_path: str | None
    query_count: int
    result_count: int
    warnings: list[str]
    metadata: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


class SemanticRetrievalProvider(Protocol):
    provider_name: str

    def dependency_status(self) -> dict[str, Any]:
        """Return semantic retrieval provider health."""

    def retrieve(
        self,
        *,
        index_path: str | None,
        query_text: str,
        limit: int,
    ) -> tuple[list[dict[str, Any]], SemanticRetrievalProviderAttempt]:
        """Retrieve reviewed/golden examples for the current document."""
