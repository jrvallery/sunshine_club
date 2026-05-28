"""Backward-compatible OCR provider imports."""

from sunshine_extraction.providers.extraction.cortex_ocr import CortexNativeOcrExecutor
from sunshine_extraction.providers.extraction.ocr_common import (
    OCR_MAX_FAILED_PAGE_RATE,
    OCR_MIN_TEXT_LENGTH,
    OCR_OK_CONFIDENCE_THRESHOLD,
    configure_tesseract_runtime,
    cortex_ocr_pages,
    cortex_root_base_url,
    failed_ocr_document,
    normalize_ocr_confidence,
    ocr_document_from_pages,
    ocr_pil_image,
    optional_int,
    shorten,
    tesseract_version,
)
from sunshine_extraction.providers.extraction.tesseract_ocr import LocalTesseractOcrExecutor

__all__ = [
    "CortexNativeOcrExecutor",
    "LocalTesseractOcrExecutor",
    "OCR_MAX_FAILED_PAGE_RATE",
    "OCR_MIN_TEXT_LENGTH",
    "OCR_OK_CONFIDENCE_THRESHOLD",
    "configure_tesseract_runtime",
    "cortex_ocr_pages",
    "cortex_root_base_url",
    "failed_ocr_document",
    "normalize_ocr_confidence",
    "ocr_document_from_pages",
    "ocr_pil_image",
    "optional_int",
    "shorten",
    "tesseract_version",
]
