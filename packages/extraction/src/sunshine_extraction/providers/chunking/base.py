"""Base contracts for document chunking providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from sunshine_extraction.services.extraction import ExtractionResult


@dataclass(frozen=True)
class ChunkingProviderAttempt:
    provider: str
    status: str
    chunk_count: int
    chunking_strategy: str
    warnings: list[str]
    metadata: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


class ChunkingProvider(Protocol):
    provider_name: str

    def dependency_status(self) -> dict[str, Any]:
        """Return chunking provider health without calling hosted services."""

    def chunk(self, extraction: ExtractionResult, quality: dict[str, Any]) -> tuple[list[dict[str, Any]], ChunkingProviderAttempt]:
        """Chunk extracted content for embedding and retrieval."""
