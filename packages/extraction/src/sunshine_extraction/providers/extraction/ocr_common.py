"""Shared OCR provider helpers."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from PIL import Image

from sunshine_extraction.domain.extraction import OcrDocumentResult, OcrPageResult
from sunshine_extraction.services.content import SampleFile

OCR_OK_CONFIDENCE_THRESHOLD = 75.0
OCR_MIN_TEXT_LENGTH = 100
OCR_MAX_FAILED_PAGE_RATE = 0.2


def ocr_pil_image(sample: SampleFile, image: Image.Image, page_number: int, page_count: int, page_start: float) -> OcrPageResult:
    import pytesseract  # type: ignore

    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    words: list[str] = []
    confidences: list[float] = []
    for text, confidence in zip(data.get("text", []), data.get("conf", []), strict=False):
        text_value = str(text).strip()
        if text_value:
            words.append(text_value)
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            continue
        if confidence_value >= 0:
            confidences.append(confidence_value)
    page_text = " ".join(words)
    return OcrPageResult(
        source_path=sample.source_path,
        relative_path=sample.relative_path,
        sample_path=str(sample.sample_path),
        page_number=page_number,
        page_count=page_count,
        ocr_engine="tesseract",
        ocr_engine_version=tesseract_version(),
        ocr_status="ok" if page_text else "empty",
        text=page_text,
        text_length=len(page_text),
        mean_confidence=round(sum(confidences) / len(confidences), 2) if confidences else None,
        word_count=len(words),
        image_width=image.width,
        image_height=image.height,
        seconds=round(time.monotonic() - page_start, 4),
        warnings=[] if page_text else ["ocr_page_text_empty"],
    )


def ocr_document_from_pages(sample: SampleFile, pages: list[OcrPageResult], seconds: float) -> OcrDocumentResult:
    page_count = len(pages)
    pages_failed = len([page for page in pages if page.ocr_status == "failed"])
    pages_ok = len([page for page in pages if page.ocr_status == "ok"])
    total_text_length = sum(page.text_length for page in pages)
    confidences = [page.mean_confidence for page in pages if page.mean_confidence is not None]
    mean_confidence = round(sum(confidences) / len(confidences), 2) if confidences else None
    warnings = sorted({warning for page in pages for warning in page.warnings})
    failed_page_rate = pages_failed / page_count if page_count else 1

    if pages_failed == page_count:
        ocr_status = "failed"
        quality = "failed"
    elif total_text_length == 0:
        ocr_status = "empty"
        quality = "metadata_only"
    elif (
        mean_confidence is not None
        and mean_confidence >= OCR_OK_CONFIDENCE_THRESHOLD
        and total_text_length >= OCR_MIN_TEXT_LENGTH
        and failed_page_rate <= OCR_MAX_FAILED_PAGE_RATE
    ):
        ocr_status = "ok"
        quality = "ok"
    else:
        ocr_status = "poor"
        quality = "poor"
        if mean_confidence is None or mean_confidence < OCR_OK_CONFIDENCE_THRESHOLD:
            warnings.append("ocr_confidence_below_threshold")
        if total_text_length < OCR_MIN_TEXT_LENGTH:
            warnings.append("ocr_sparse_text_below_threshold")
        if failed_page_rate > OCR_MAX_FAILED_PAGE_RATE:
            warnings.append("ocr_failed_page_rate_above_threshold")

    return OcrDocumentResult(
        source_path=sample.source_path,
        relative_path=sample.relative_path,
        sample_path=str(sample.sample_path),
        ocr_status=ocr_status,
        page_count=page_count,
        pages_ok=pages_ok,
        pages_failed=pages_failed,
        total_text_length=total_text_length,
        mean_confidence=mean_confidence,
        quality=quality,
        seconds=round(seconds, 4),
        warnings=warnings,
    )


def failed_ocr_document(sample: SampleFile, warnings: list[str]) -> OcrDocumentResult:
    return OcrDocumentResult(
        source_path=sample.source_path,
        relative_path=sample.relative_path,
        sample_path=str(sample.sample_path),
        ocr_status="failed",
        page_count=0,
        pages_ok=0,
        pages_failed=0,
        total_text_length=0,
        mean_confidence=None,
        quality="failed",
        seconds=0,
        warnings=warnings,
    )


def tesseract_version() -> str | None:
    try:
        configure_tesseract_runtime()
        import pytesseract  # type: ignore

        return str(pytesseract.get_tesseract_version())
    except Exception:  # noqa: BLE001
        return None


def configure_tesseract_runtime() -> str | None:
    binary = shutil.which("tesseract")
    if binary:
        return binary

    local_root = Path.cwd() / ".local" / "tesseract"
    local_binary = local_root / "usr" / "bin" / "tesseract"
    local_lib = local_root / "usr" / "lib" / "x86_64-linux-gnu"
    local_tessdata = local_root / "usr" / "share" / "tesseract-ocr" / "5" / "tessdata"
    if not local_binary.exists():
        return None

    os.environ["PATH"] = f"{local_binary.parent}:{os.environ.get('PATH', '')}"
    os.environ["LD_LIBRARY_PATH"] = f"{local_lib}:{os.environ.get('LD_LIBRARY_PATH', '')}"
    if local_tessdata.exists():
        os.environ["TESSDATA_PREFIX"] = str(local_tessdata)
    try:
        import pytesseract  # type: ignore

        pytesseract.pytesseract.tesseract_cmd = str(local_binary)
    except Exception:  # noqa: BLE001
        pass
    return str(local_binary)


def cortex_root_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[:-3].rstrip("/")
    return normalized


def cortex_ocr_pages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    pages = payload.get("pages")
    if isinstance(pages, list):
        return [page for page in pages if isinstance(page, dict)]
    result = payload.get("result")
    if isinstance(result, dict):
        result_pages = result.get("pages")
        if isinstance(result_pages, list):
            return [page for page in result_pages if isinstance(page, dict)]
    data = payload.get("data")
    if isinstance(data, dict):
        data_pages = data.get("pages")
        if isinstance(data_pages, list):
            return [page for page in data_pages if isinstance(page, dict)]
    return []


def normalize_ocr_confidence(value: Any) -> float | None:
    if not isinstance(value, int | float):
        return None
    confidence = float(value)
    if confidence <= 1.0:
        confidence *= 100
    return round(max(0.0, min(confidence, 100.0)), 2)


def optional_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def shorten(text: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."
