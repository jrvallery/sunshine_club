"""Extraction service exports."""

from sunshine_extraction.domain.extraction import ExtractionResult, OcrArtifacts, OcrExecutor
from sunshine_extraction.services.extraction.core import extract_content, ocr_executor_from_env
from sunshine_extraction.services.extraction.escalation import validate_and_repair_extraction
from sunshine_extraction.services.quality.gates import extraction_quality_gate
from sunshine_extraction.services.quality.text_validation import validate_extracted_text


def __getattr__(name: str):
    if name == "chunk_content":
        from sunshine_extraction.providers.chunking.legacy import chunk_content

        return chunk_content
    raise AttributeError(name)


__all__ = [
    "ExtractionResult",
    "OcrArtifacts",
    "OcrExecutor",
    "chunk_content",
    "extract_content",
    "extraction_quality_gate",
    "ocr_executor_from_env",
    "validate_extracted_text",
    "validate_and_repair_extraction",
]
