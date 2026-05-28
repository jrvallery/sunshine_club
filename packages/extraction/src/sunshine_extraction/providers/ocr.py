"""Local OCR executor implementations."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from PIL import Image

from sunshine_extraction.config import DEFAULT_CORTEX_BASE_URL, DEFAULT_CORTEX_OCR_MODEL
from sunshine_extraction.cortex import CortexClient
from sunshine_extraction.domain.extraction import OcrDocumentResult, OcrExecutor, OcrPageResult
from sunshine_extraction.services.content import IMAGE_EXTENSIONS, SampleFile

OCR_OK_CONFIDENCE_THRESHOLD = 75.0
OCR_MIN_TEXT_LENGTH = 100
OCR_MAX_FAILED_PAGE_RATE = 0.2


class LocalTesseractOcrExecutor(OcrExecutor):
    def dependency_status(self) -> dict[str, Any]:
        tesseract_binary = configure_tesseract_runtime()
        status: dict[str, Any] = {
            "engine": "tesseract",
            "tesseract_binary": tesseract_binary,
            "pytesseract_available": False,
            "pypdfium2_available": False,
            "engine_version": None,
            "missing": [],
        }
        try:
            import pytesseract  # type: ignore

            status["pytesseract_available"] = True
            try:
                status["engine_version"] = str(pytesseract.get_tesseract_version())
            except Exception:  # noqa: BLE001
                status["engine_version"] = "unknown"
        except Exception:  # noqa: BLE001
            status["missing"].append("pytesseract")
        try:
            import pypdfium2  # noqa: F401

            status["pypdfium2_available"] = True
        except Exception:  # noqa: BLE001
            status["missing"].append("pypdfium2")
        if not tesseract_binary:
            status["missing"].append("tesseract")
        return status

    def ocr_sample(self, sample: SampleFile, plan: dict[str, Any]) -> tuple[OcrDocumentResult, list[OcrPageResult]]:
        status = self.dependency_status()
        if status["missing"]:
            return self._deferred_document(sample, status), []
        if sample.sample_path.suffix.lower() in IMAGE_EXTENSIONS:
            return self._ocr_images(sample, [Image.open(sample.sample_path)])
        if sample.sample_path.suffix.lower() == ".pdf":
            return self._ocr_pdf(sample)
        return self._failed_document(sample, ["ocr_unsupported_file_type"]), []

    def _ocr_pdf(self, sample: SampleFile) -> tuple[OcrDocumentResult, list[OcrPageResult]]:
        try:
            import pypdfium2 as pdfium  # type: ignore

            pdf = pdfium.PdfDocument(str(sample.sample_path))
            images = []
            for page in pdf:
                bitmap = page.render(scale=2)
                images.append(bitmap.to_pil())
            return self._ocr_images(sample, images)
        except Exception as error:  # noqa: BLE001
            return self._failed_document(sample, [f"pdf_rasterization_failed:{type(error).__name__}"]), []

    def _ocr_images(self, sample: SampleFile, images: list[Image.Image]) -> tuple[OcrDocumentResult, list[OcrPageResult]]:
        page_count = len(images)
        pages: list[OcrPageResult] = []
        start = time.monotonic()
        for index, image in enumerate(images, start=1):
            page_start = time.monotonic()
            try:
                pages.append(ocr_pil_image(sample, image, index, page_count, page_start))
            except Exception as error:  # noqa: BLE001
                pages.append(
                    OcrPageResult(
                        source_path=sample.source_path,
                        relative_path=sample.relative_path,
                        sample_path=str(sample.sample_path),
                        page_number=index,
                        page_count=page_count,
                        ocr_engine="tesseract",
                        ocr_engine_version=tesseract_version(),
                        ocr_status="failed",
                        text="",
                        text_length=0,
                        mean_confidence=None,
                        word_count=0,
                        image_width=getattr(image, "width", None),
                        image_height=getattr(image, "height", None),
                        seconds=round(time.monotonic() - page_start, 4),
                        warnings=[f"ocr_page_failed:{type(error).__name__}"],
                    )
                )
            finally:
                image.close()
        return ocr_document_from_pages(sample, pages, time.monotonic() - start), pages

    def _deferred_document(self, sample: SampleFile, status: dict[str, Any]) -> OcrDocumentResult:
        return OcrDocumentResult(
            source_path=sample.source_path,
            relative_path=sample.relative_path,
            sample_path=str(sample.sample_path),
            ocr_status="deferred",
            page_count=0,
            pages_ok=0,
            pages_failed=0,
            total_text_length=0,
            mean_confidence=None,
            quality="deferred",
            seconds=0,
            warnings=["ocr_executor_not_installed", *[f"missing:{item}" for item in status["missing"]]],
        )

    def _failed_document(self, sample: SampleFile, warnings: list[str]) -> OcrDocumentResult:
        return failed_ocr_document(sample, warnings)


class CortexNativeOcrExecutor(OcrExecutor):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_CORTEX_BASE_URL,
        model: str = DEFAULT_CORTEX_OCR_MODEL,
        timeout_seconds: float = 300,
    ) -> None:
        if not api_key:
            raise ValueError("CORTEX_API_KEY is required for Cortex OCR")
        self.api_key = api_key
        self.base_url = cortex_root_base_url(base_url)
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.engine_name = f"cortex:{model}"

    def dependency_status(self) -> dict[str, Any]:
        return {
            "engine": "cortex",
            "model": self.model,
            "base_url": self.base_url,
            "missing": [] if self.api_key else ["api_key"],
        }

    def ocr_sample(self, sample: SampleFile, plan: dict[str, Any]) -> tuple[OcrDocumentResult, list[OcrPageResult]]:
        start = time.monotonic()
        try:
            payload = self._ocr_file(sample.sample_path)
        except Exception as error:  # noqa: BLE001
            return failed_ocr_document(sample, [f"ocr_fallback_failed:{type(error).__name__}"]), []

        pages_payload = cortex_ocr_pages(payload)
        if not pages_payload:
            text = str(payload.get("text") or payload.get("output_text") or "").strip()
            pages_payload = [{"page_number": 1, "text": text, "confidence": payload.get("confidence")}]

        page_count = len(pages_payload)
        pages: list[OcrPageResult] = []
        for index, page_payload in enumerate(pages_payload, start=1):
            page_number = int(page_payload.get("page_number") or page_payload.get("page") or index)
            text = str(page_payload.get("text") or page_payload.get("content") or "").strip()
            confidence = normalize_ocr_confidence(page_payload.get("confidence") or page_payload.get("mean_confidence"))
            warnings = [f"ocr_model_used:{self.engine_name}"]
            notes = page_payload.get("notes")
            if isinstance(notes, str) and notes.strip():
                warnings.append(f"ocr_fallback_note:{shorten(notes, 120)}")
            pages.append(
                OcrPageResult(
                    source_path=sample.source_path,
                    relative_path=sample.relative_path,
                    sample_path=str(sample.sample_path),
                    page_number=page_number,
                    page_count=page_count,
                    ocr_engine=self.engine_name,
                    ocr_engine_version=self.model,
                    ocr_status="ok" if text else "empty",
                    text=text,
                    text_length=len(text),
                    mean_confidence=confidence,
                    word_count=len(text.split()),
                    image_width=optional_int(page_payload.get("image_width") or page_payload.get("width")),
                    image_height=optional_int(page_payload.get("image_height") or page_payload.get("height")),
                    seconds=round(time.monotonic() - start, 4),
                    warnings=warnings,
                )
            )
        return ocr_document_from_pages(sample, pages, time.monotonic() - start), pages

    def _ocr_file(self, path: Path) -> dict[str, Any]:
        return CortexClient(base_url=self.base_url, api_key=self.api_key, timeout_seconds=self.timeout_seconds).ocr_file(path, model=self.model)


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
