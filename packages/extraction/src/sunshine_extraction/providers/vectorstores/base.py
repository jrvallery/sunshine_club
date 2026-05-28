"""Base contracts for local vector stores."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class VectorStoreUpsertResult:
    provider: str
    collection: str | None
    status: str
    indexed_count: int
    skipped_count: int
    warnings: list[str]
    metadata: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


class VectorStoreProvider(Protocol):
    provider_name: str

    def dependency_status(self) -> dict[str, Any]:
        """Return local vector-store dependency health."""

    def upsert_embeddings(self, chunks: list[dict[str, Any]], embeddings: list[dict[str, Any]]) -> VectorStoreUpsertResult:
        """Persist chunk embeddings in a local vector index."""

