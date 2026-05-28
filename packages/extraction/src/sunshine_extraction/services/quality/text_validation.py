"""Text validation service for extracted content."""

from __future__ import annotations

import re
from typing import Any

from sunshine_extraction.domain.extraction import ExtractionResult
from sunshine_extraction.services.content import SampleFile

OCR_MIN_TEXT_LENGTH = 100


def validate_extracted_text(extraction: ExtractionResult) -> dict[str, Any]:
    """Detect text extraction failures that should be repaired with OCR."""

    text = extraction.text.strip()
    if extraction.extraction_status != "extracted" or not text:
        return {"status": "not_applicable", "reason": None}
    if len(text) < OCR_MIN_TEXT_LENGTH:
        return {"status": "ok", "reason": None}
    if _looks_like_table_distortion(text):
        return {"status": "failed", "reason": "table_distortion_suspected"}
    if _looks_like_gibberish(text):
        return {"status": "failed", "reason": "gibberish_suspected"}
    return {"status": "ok", "reason": None}


def validation_row(sample: SampleFile, extraction: ExtractionResult, validation: dict[str, Any]) -> dict[str, Any]:
    """Normalize validation output for `sample-extraction-validations.jsonl`."""

    return {
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
        "sample_path": str(sample.sample_path),
        "status": validation.get("status"),
        "reason": validation.get("reason"),
        "strategy": extraction.plan.get("strategy"),
        "extraction_status": extraction.extraction_status,
        "text_length": len(extraction.text or ""),
    }


def with_text_validation(extraction: ExtractionResult, validation: dict[str, Any]) -> ExtractionResult:
    """Attach validation metadata to an extraction result without changing text."""

    return type(extraction)(
        sample=extraction.sample,
        plan=extraction.plan,
        extraction_status=extraction.extraction_status,
        text=extraction.text,
        metadata={**extraction.metadata, "text_validation": validation},
        page_count=extraction.page_count,
        warnings=extraction.warnings,
    )


def _looks_like_gibberish(text: str) -> bool:
    compact = text.strip()
    if len(compact) < OCR_MIN_TEXT_LENGTH:
        return False
    tokens = re.findall(r"[A-Za-z0-9'/$.,:-]+", compact)
    if len(tokens) < 20:
        return False
    odd_character_ratio = len(re.findall(r"[^A-Za-z0-9\\s.,:$%/'\"()&+-]", compact)) / max(len(compact), 1)
    alpha_tokens = [token for token in tokens if re.search(r"[A-Za-z]", token)]
    vowel_tokens = [token for token in alpha_tokens if re.search(r"[aeiouAEIOU]", token)]
    vowel_token_ratio = len(vowel_tokens) / max(len(alpha_tokens), 1)
    long_token_ratio = len([token for token in tokens if len(token) > 18]) / len(tokens)
    return odd_character_ratio > 0.3 or (len(alpha_tokens) >= 15 and vowel_token_ratio < 0.2) or long_token_ratio > 0.3


def _looks_like_table_distortion(text: str) -> bool:
    compact = text.strip()
    if len(compact) < 300:
        return False
    lines = [line.strip() for line in compact.splitlines() if line.strip()]
    if len(lines) < 6:
        return False
    table_symbol_count = len(re.findall(r"[_|]{2,}|[|]{1}|[-=]{4,}", compact))
    numeric_tokens = re.findall(r"\b\d[\d,.$%'-]*\b", compact)
    alpha_words = re.findall(r"\b[A-Za-z]{3,}\b", compact)
    sentence_markers = len(re.findall(r"[.!?]\s+[A-Z]", compact))
    dense_symbol_lines = sum(1 for line in lines if len(re.findall(r"[_|=-]", line)) >= 4)
    short_alpha_ratio = len(alpha_words) / max(len(numeric_tokens) + table_symbol_count, 1)
    return (
        dense_symbol_lines >= max(4, len(lines) // 3)
        and table_symbol_count >= 18
        and len(numeric_tokens) >= 15
        and sentence_markers <= 2
        and short_alpha_ratio < 0.8
    )
