"""Chunk row contracts for retrieval and embedding artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sunshine_extraction.domain.extraction import ExtractionResult


@dataclass(frozen=True)
class DocumentChunk:
    source_path: str
    relative_path: str
    sample_path: str
    chunk_id: str
    chunk_index: int
    chunk_kind: str
    text: str
    metadata: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


def chunk_row(
    extraction: ExtractionResult,
    chunk_index: int,
    chunk_kind: str,
    text: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return DocumentChunk(
        source_path=extraction.sample.source_path,
        relative_path=extraction.sample.relative_path,
        sample_path=str(extraction.sample.sample_path),
        chunk_id=f"{extraction.sample.sample_group}:{extraction.sample.sample_number or 0}:{chunk_index}",
        chunk_index=chunk_index,
        chunk_kind=chunk_kind,
        text=text,
        metadata=metadata,
    ).as_row()
