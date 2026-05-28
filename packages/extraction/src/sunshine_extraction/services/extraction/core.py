"""Core extraction and OCR dispatch services."""

from __future__ import annotations

from typing import Any

from PIL import Image
from pypdf import PdfReader

from sunshine_extraction.domain.extraction import ExtractionResult, OcrArtifacts, OcrExecutor
from sunshine_extraction.providers.extraction.cortex_ocr import CortexNativeOcrExecutor
from sunshine_extraction.providers.extraction.native_text import extract_text
from sunshine_extraction.providers.extraction.photo_metadata import extract_photo_metadata
from sunshine_extraction.providers.extraction.spreadsheet import extract_spreadsheet_metadata
from sunshine_extraction.providers.extraction.tesseract_ocr import LocalTesseractOcrExecutor
from sunshine_extraction.services.content import IMAGE_EXTENSIONS, SampleFile


def extract_content(
    sample: SampleFile,
    plan: dict[str, Any],
    *,
    ocr_executor: OcrExecutor | None = None,
    ocr_artifacts: OcrArtifacts | None = None,
) -> ExtractionResult:
    if not sample.sample_path.exists():
        return ExtractionResult(sample, plan, "failed", "", {"missing_sample_path": str(sample.sample_path)}, None, ["sample_file_missing"])

    strategy = plan["strategy"]
    if strategy == "deferred_technical":
        return ExtractionResult(
            sample,
            plan,
            "deferred_technical",
            "",
            {"defer_reason": plan.get("defer_reason")},
            None,
            [f"deferred_technical:{plan.get('defer_reason') or 'unknown'}"],
        )
    if strategy == "photo_metadata":
        return extract_photo_metadata(sample, plan)
    if strategy == "text_extraction":
        return extract_text(sample, plan)
    if strategy == "spreadsheet_table_extraction":
        return extract_spreadsheet_metadata(sample, plan)
    if strategy == "ocr_page_level":
        return extract_ocr_page_level(sample, plan, ocr_executor=ocr_executor, ocr_artifacts=ocr_artifacts)
    return ExtractionResult(sample, plan, "failed", "", {}, None, [f"unsupported_strategy:{strategy}"])


def ocr_executor_from_env(*, fallback_provider_override: str | None = None) -> OcrExecutor:
    import os

    from sunshine_extraction.config import DEFAULT_CORTEX_BASE_URL, DEFAULT_CORTEX_OCR_MODEL

    provider_name = (fallback_provider_override or os.environ.get("SUNSHINE_OCR_FALLBACK_PROVIDER", "cortex")).strip().lower()
    if provider_name in {"", "disabled", "none", "local"}:
        return LocalTesseractOcrExecutor()
    timeout_seconds = float(os.environ.get("SUNSHINE_OCR_FALLBACK_TIMEOUT_SECONDS", "120"))
    if provider_name == "openai":
        return LocalTesseractOcrExecutor()
    if provider_name in {"cortex", "openai-compatible"}:
        try:
            return CortexNativeOcrExecutor(
                api_key=os.environ.get("SUNSHINE_OCR_FALLBACK_API_KEY") or os.environ.get("CORTEX_API_KEY") or os.environ.get("CORTEX_OPENAI_API_KEY", ""),
                model=os.environ.get("SUNSHINE_OCR_FALLBACK_MODEL") or os.environ.get("CORTEX_OCR_MODEL", DEFAULT_CORTEX_OCR_MODEL),
                base_url=os.environ.get("SUNSHINE_OCR_FALLBACK_BASE_URL") or os.environ.get("CORTEX_BASE_URL", DEFAULT_CORTEX_BASE_URL),
                timeout_seconds=timeout_seconds,
            )
        except ValueError:
            return LocalTesseractOcrExecutor()
    return LocalTesseractOcrExecutor()


def extract_ocr_page_level(
    sample: SampleFile,
    plan: dict[str, Any],
    *,
    ocr_executor: OcrExecutor | None,
    ocr_artifacts: OcrArtifacts | None,
) -> ExtractionResult:
    executor = ocr_executor or LocalTesseractOcrExecutor()
    document, pages = executor.ocr_sample(sample, plan)
    if ocr_artifacts is not None:
        ocr_artifacts.pages.extend(page.as_row() for page in pages)
        ocr_artifacts.documents.append(document.as_row())

    metadata: dict[str, Any] = {
        "ocr_required": True,
        "document_subtype": plan.get("document_subtype"),
        "ocr_document": document.as_row(),
    }
    if document.ocr_status == "deferred":
        metadata.update(ocr_probe_metadata(sample))
        return ExtractionResult(
            sample,
            plan,
            "deferred_extractor",
            "",
            metadata,
            document.page_count or metadata.get("page_count"),
            document.warnings or ["ocr_executor_not_installed"],
        )
    if document.ocr_status == "failed":
        return ExtractionResult(sample, plan, "failed", "", metadata, document.page_count, document.warnings or ["ocr_failed"])

    text = "\n\n".join(page.text for page in pages if page.text.strip())
    if text.strip():
        return ExtractionResult(
            sample,
            plan,
            "extracted",
            text,
            metadata,
            document.page_count,
            document.warnings,
        )
    return ExtractionResult(
        sample,
        plan,
        "metadata_extracted",
        "",
        metadata,
        document.page_count,
        document.warnings or ["ocr_text_empty"],
    )


def ocr_probe_metadata(sample: SampleFile) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    page_count = sample.index_row.get("metadata", {}).get("page_count")
    if isinstance(page_count, int):
        metadata["page_count"] = page_count
    if sample.sample_path.suffix.lower() in IMAGE_EXTENSIONS:
        try:
            with Image.open(sample.sample_path) as image:
                metadata.update(
                    {
                        "image_format": image.format,
                        "width": image.width,
                        "height": image.height,
                        "mode": image.mode,
                        "frame_count": getattr(image, "n_frames", 1),
                    }
                )
        except Exception as error:  # noqa: BLE001
            metadata["image_probe_error"] = str(error)
    elif sample.sample_path.suffix.lower() == ".pdf":
        try:
            reader = PdfReader(str(sample.sample_path))
            metadata["page_count"] = len(reader.pages)
        except Exception as error:  # noqa: BLE001
            metadata["pdf_probe_error"] = str(error)
    return metadata
