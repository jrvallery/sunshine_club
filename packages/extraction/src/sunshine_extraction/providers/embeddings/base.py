"""Base contracts for chunk embedding providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ChunkEmbeddingProviderAttempt:
    provider: str
    model: str
    status: str
    requested_count: int
    embedded_count: int
    dimensions: int | None
    semantic_quality: bool
    warnings: list[str]
    metadata: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


class ChunkEmbeddingProvider(Protocol):
    provider_name: str

    def dependency_status(self) -> dict[str, Any]:
        """Return embedding provider health without embedding source documents."""

    def embed_chunks(
        self,
        chunks: list[dict[str, Any]],
        *,
        failure_mode: str,
    ) -> tuple[list[dict[str, Any]], ChunkEmbeddingProviderAttempt]:
        """Embed chunks and return normalized embedding rows plus provider attempt metadata."""
