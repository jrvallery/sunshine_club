"""Conservative logical document segmentation for long scanned files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sunshine_extraction.domain.document_segments import DocumentSegment
from sunshine_extraction.services.extraction import ExtractionResult


def propose_document_segments(
    extraction: ExtractionResult,
    *,
    file_id: str | None = None,
    content_class: dict[str, Any] | None = None,
    ocr_pages: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    pages = ocr_pages or []
    page_count = _page_count(extraction, pages)
    segment_type, evidence = _segment_type_and_evidence(extraction, content_class or {})
    requires_review = _requires_segment_review(extraction, page_count, segment_type)
    segment = DocumentSegment(
        segment_id=_segment_id(extraction, 1),
        parent_file_id=file_id,
        source_path=extraction.sample.source_path,
        relative_path=extraction.sample.relative_path,
        sample_path=str(extraction.sample.sample_path),
        page_start=1 if page_count else None,
        page_end=page_count or None,
        segment_index=1,
        segment_type=segment_type,
        segment_title=Path(extraction.sample.relative_path).name,
        segment_confidence=0.55 if requires_review else 0.8,
        segment_boundary_evidence=evidence,
        requires_segment_review=requires_review,
        metadata={
            "policy": "conservative_single_segment",
            "page_count": page_count,
            "text_length": len(extraction.text or ""),
            "content_class": (content_class or {}).get("final_class"),
            "future_split_candidate": requires_review,
        },
    )
    return [segment.as_row()]


def attach_segment_ids_to_chunks(chunks: list[dict[str, Any]], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not chunks or not segments:
        return chunks
    if len(segments) != 1:
        return chunks
    segment_id = segments[0]["segment_id"]
    return [{**chunk, "segment_id": segment_id, "parent_segment_id": segment_id} for chunk in chunks]


def _page_count(extraction: ExtractionResult, pages: list[dict[str, Any]]) -> int:
    if extraction.page_count:
        return int(extraction.page_count)
    if pages:
        return max(int(page.get("page_count") or page.get("page_number") or 0) for page in pages)
    ocr_document = extraction.metadata.get("ocr_document")
    if isinstance(ocr_document, dict) and ocr_document.get("page_count"):
        return int(ocr_document["page_count"])
    return 0


def _segment_type_and_evidence(extraction: ExtractionResult, content_class: dict[str, Any]) -> tuple[str, list[str]]:
    signals = " ".join(
        [
            extraction.sample.relative_path,
            extraction.sample.sample_path.name,
            str(extraction.plan.get("document_subtype") or ""),
            str(content_class.get("final_class") or ""),
        ]
    ).lower()
    if "scrapbook" in signals:
        return "scrapbook_page_group", ["matched:scrapbook"]
    if "newspaper" in signals or "ledger" in signals or "article" in signals:
        return "newspaper_article_group", ["matched:newspaper_or_article"]
    if "budget" in signals or "treasurer" in signals or "financial" in signals:
        return "financial_packet_section", ["matched:financial_packet"]
    if "minutes" in signals or "agenda" in signals:
        return "meeting_packet_section", ["matched:meeting_packet"]
    return "single_document", ["default:single_document"]


def _requires_segment_review(extraction: ExtractionResult, page_count: int, segment_type: str) -> bool:
    if segment_type in {"scrapbook_page_group", "newspaper_article_group"} and page_count > 1:
        return True
    if page_count >= 10:
        return True
    return False


def _segment_id(extraction: ExtractionResult, segment_index: int) -> str:
    base = f"{extraction.sample.sample_group}:{extraction.sample.sample_number or 0}"
    return f"{base}:segment-{segment_index:03d}"
