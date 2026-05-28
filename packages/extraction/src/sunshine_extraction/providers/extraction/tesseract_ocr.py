"""Local Tesseract OCR provider."""

from __future__ import annotations

import time
from typing import Any

from PIL import Image

from sunshine_extraction.domain.extraction import OcrDocumentResult, OcrExecutor, OcrPageResult
from sunshine_extraction.providers.extraction.ocr_common import (
    configure_tesseract_runtime,
    failed_ocr_document,
    ocr_document_from_pages,
    ocr_pil_image,
    tesseract_version,
)
from sunshine_extraction.services.content import IMAGE_EXTENSIONS, SampleFile


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
