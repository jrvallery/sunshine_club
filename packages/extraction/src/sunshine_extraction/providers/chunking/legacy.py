"""Legacy fixed-size chunking implementation."""

from __future__ import annotations

import json
from typing import Any

from sunshine_extraction.services.extraction import ExtractionResult


def chunk_content(extraction: ExtractionResult, quality: dict[str, Any], *, chunk_size: int = 1800) -> list[dict[str, Any]]:
    """Create backward-compatible text/metadata chunks."""

    if not quality["can_chunk"]:
        return []
    if extraction.text.strip():
        chunks = []
        text = extraction.text.strip()
        for index, start in enumerate(range(0, len(text), chunk_size), start=1):
            chunk_text = text[start : start + chunk_size]
            chunks.append(_chunk_row(extraction, index, "text", chunk_text, {"char_start": start, "char_end": start + len(chunk_text)}))
        return chunks

    metadata_text = json.dumps(extraction.metadata, sort_keys=True)
    if extraction.extraction_status == "deferred_extractor":
        metadata_text = f"OCR deferred for {extraction.sample.relative_path}. Metadata: {metadata_text}"
    return [_chunk_row(extraction, 1, "metadata", metadata_text, extraction.metadata)]


def _chunk_row(extraction: ExtractionResult, chunk_index: int, chunk_kind: str, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": extraction.sample.source_path,
        "relative_path": extraction.sample.relative_path,
        "sample_path": str(extraction.sample.sample_path),
        "chunk_id": f"{extraction.sample.sample_group}:{extraction.sample.sample_number or 0}:{chunk_index}",
        "chunk_index": chunk_index,
        "chunk_kind": chunk_kind,
        "text": text,
        "metadata": metadata,
    }
