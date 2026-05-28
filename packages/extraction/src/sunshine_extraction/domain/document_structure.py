"""Normalized document structure contracts.

These rows are intentionally provider-neutral so Docling, native text, OCR, and
future parsers can feed chunking/segmentation without leaking raw provider
objects through the graph state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DocumentStructure:
    source_path: str
    relative_path: str
    sample_path: str
    provider: str
    page_count: int | None
    text_length: int
    sections: list[dict[str, Any]]
    pages: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    figures: list[dict[str, Any]]
    metadata: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        return asdict(self)

