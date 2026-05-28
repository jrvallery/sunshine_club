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
    document_structure: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    pages = ocr_pages or []
    page_count = _page_count(extraction, pages, document_structure or {})
    segment_type, evidence = _segment_type_and_evidence(extraction, content_class or {})
    if _should_emit_candidate_splits(page_count, segment_type):
        split_segments = _candidate_split_segments(
            extraction,
            file_id=file_id,
            segment_type=segment_type,
            evidence=evidence,
            page_count=page_count,
            pages=_normalized_pages(pages, page_count),
        )
        if split_segments:
            return [segment.as_row() for segment in split_segments]
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


def _page_count(extraction: ExtractionResult, pages: list[dict[str, Any]], document_structure: dict[str, Any]) -> int:
    if extraction.page_count:
        return int(extraction.page_count)
    if pages:
        return max(int(page.get("page_count") or page.get("page_number") or 0) for page in pages)
    if document_structure.get("page_count"):
        return int(document_structure["page_count"])
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


def _should_emit_candidate_splits(page_count: int, segment_type: str) -> bool:
    return page_count > 1 and segment_type in {"scrapbook_page_group", "newspaper_article_group"}


def _candidate_split_segments(
    extraction: ExtractionResult,
    *,
    file_id: str | None,
    segment_type: str,
    evidence: list[str],
    page_count: int,
    pages: list[dict[str, Any]],
) -> list[DocumentSegment]:
    groups = _separator_page_groups(pages, page_count)
    if len(groups) < 2:
        groups = _page_level_groups(page_count) if page_count <= 50 else _fixed_page_windows(page_count, window_size=10)

    child_type = "scrapbook_page" if segment_type == "scrapbook_page_group" else "newspaper_article"
    policy = "separator_page_groups" if any(
        any("blank_separator" in evidence_item for evidence_item in group["evidence"])
        for group in groups
    ) else "page_level_review_candidates"
    if page_count > 50 and policy == "page_level_review_candidates":
        policy = "fixed_page_window_review_candidates"

    return [
        DocumentSegment(
            segment_id=_segment_id(extraction, index),
            parent_file_id=file_id,
            source_path=extraction.sample.source_path,
            relative_path=extraction.sample.relative_path,
            sample_path=str(extraction.sample.sample_path),
            page_start=group["page_start"],
            page_end=group["page_end"],
            segment_index=index,
            segment_type=child_type if group["page_start"] == group["page_end"] else segment_type,
            segment_title=_segment_title(extraction, group["page_start"], group["page_end"]),
            segment_confidence=0.45 if policy == "separator_page_groups" else 0.35,
            segment_boundary_evidence=[*evidence, *group["evidence"], f"policy:{policy}"],
            requires_segment_review=True,
            metadata={
                "policy": policy,
                "parent_page_count": page_count,
                "page_count": group["page_end"] - group["page_start"] + 1,
                "page_text_length": group.get("text_length", 0),
                "page_word_count": group.get("word_count", 0),
                "text_snippet": group.get("text_snippet", ""),
                "source_segment_type": segment_type,
            },
        )
        for index, group in enumerate(groups, start=1)
    ]


def _normalized_pages(pages: list[dict[str, Any]], page_count: int) -> list[dict[str, Any]]:
    by_number = {
        int(page.get("page_number") or 0): page
        for page in pages
        if isinstance(page.get("page_number"), int) or str(page.get("page_number") or "").isdigit()
    }
    return [by_number.get(index, {"page_number": index, "text": "", "text_length": 0, "word_count": 0}) for index in range(1, page_count + 1)]


def _separator_page_groups(pages: list[dict[str, Any]], page_count: int) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    start: int | None = None
    text_length = 0
    word_count = 0
    snippets: list[str] = []
    saw_separator = False

    for page in pages:
        page_number = int(page.get("page_number") or 0)
        if page_number < 1:
            continue
        if _is_blank_separator(page):
            saw_separator = True
            if start is not None:
                groups.append(_group(start, page_number - 1, text_length, word_count, snippets, ["blank_separator_page"]))
                start = None
                text_length = 0
                word_count = 0
                snippets = []
            continue
        if start is None:
            start = page_number
        text_length += int(page.get("text_length") or len(str(page.get("text") or "")))
        word_count += int(page.get("word_count") or len(str(page.get("text") or "").split()))
        if page.get("text") and len(" ".join(snippets)) < 220:
            snippets.append(str(page["text"]).strip().replace("\n", " ")[:220])

    if start is not None:
        groups.append(_group(start, page_count, text_length, word_count, snippets, ["blank_separator_page"] if saw_separator else []))
    return groups if saw_separator else []


def _page_level_groups(page_count: int) -> list[dict[str, Any]]:
    return [_group(page, page, 0, 0, [], ["page_boundary_candidate"]) for page in range(1, page_count + 1)]


def _fixed_page_windows(page_count: int, *, window_size: int) -> list[dict[str, Any]]:
    return [
        _group(page, min(page + window_size - 1, page_count), 0, 0, [], ["fixed_page_window_candidate"])
        for page in range(1, page_count + 1, window_size)
    ]


def _group(
    page_start: int,
    page_end: int,
    text_length: int,
    word_count: int,
    snippets: list[str],
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "page_start": page_start,
        "page_end": page_end,
        "text_length": text_length,
        "word_count": word_count,
        "text_snippet": " ".join(snippets).strip(),
        "evidence": evidence,
    }


def _is_blank_separator(page: dict[str, Any]) -> bool:
    text = str(page.get("text") or "").strip()
    text_length = int(page.get("text_length") or len(text))
    word_count = int(page.get("word_count") or len(text.split()))
    warnings = set(page.get("warnings") or [])
    if "ocr_page_text_empty" in warnings:
        return True
    return text_length <= 8 and word_count <= 2


def _segment_title(extraction: ExtractionResult, page_start: int, page_end: int) -> str:
    filename = Path(extraction.sample.relative_path).name
    if page_start == page_end:
        return f"{filename} p{page_start}"
    return f"{filename} pp{page_start}-{page_end}"


def _segment_id(extraction: ExtractionResult, segment_index: int) -> str:
    base = f"{extraction.sample.sample_group}:{extraction.sample.sample_number or 0}"
    return f"{base}:segment-{segment_index:03d}"
