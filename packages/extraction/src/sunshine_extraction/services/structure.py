"""Normalize extraction/provider output into a stable structure artifact."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.domain.document_structure import DocumentStructure
from sunshine_extraction.services.extraction import ExtractionResult


def normalize_document_structure(
    extraction: ExtractionResult,
    *,
    ocr_pages: list[dict[str, Any]] | None = None,
    provider_attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pages = _pages(extraction, ocr_pages or [])
    sections = _sections(extraction)
    provider = _provider(extraction, provider_attempts or [])
    structure = DocumentStructure(
        source_path=extraction.sample.source_path,
        relative_path=extraction.sample.relative_path,
        sample_path=str(extraction.sample.sample_path),
        provider=provider,
        page_count=extraction.page_count or (len(pages) if pages else None),
        text_length=len(extraction.text or ""),
        sections=sections,
        pages=pages,
        tables=[],
        figures=[],
        metadata={
            "extraction_status": extraction.extraction_status,
            "strategy": extraction.plan.get("strategy"),
            "document_subtype": extraction.plan.get("document_subtype"),
            "structure_policy": "v2_basic_text_page_normalization",
        },
    )
    return structure.as_row()


def _pages(extraction: ExtractionResult, ocr_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if ocr_pages:
        return [
            {
                "page_number": page.get("page_number"),
                "text_length": page.get("text_length"),
                "word_count": page.get("word_count"),
                "quality": page.get("ocr_status"),
                "mean_confidence": page.get("mean_confidence"),
            }
            for page in ocr_pages
        ]
    if extraction.text.strip():
        return [{"page_number": 1, "text_length": len(extraction.text), "word_count": len(extraction.text.split()), "quality": "text"}]
    if extraction.metadata:
        return [{"page_number": None, "text_length": 0, "word_count": 0, "quality": "metadata"}]
    return []


def _sections(extraction: ExtractionResult) -> list[dict[str, Any]]:
    text = extraction.text.strip()
    if not text:
        return []
    title = extraction.sample.sample_path.name
    return [
        {
            "section_index": 1,
            "title": title,
            "char_start": 0,
            "char_end": len(text),
            "text_length": len(text),
        }
    ]


def _provider(extraction: ExtractionResult, provider_attempts: list[dict[str, Any]]) -> str:
    if extraction.metadata.get("provider"):
        return str(extraction.metadata["provider"])
    if provider_attempts:
        return str(provider_attempts[-1].get("provider") or "unknown")
    return "current"
