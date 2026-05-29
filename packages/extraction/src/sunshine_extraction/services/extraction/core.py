"""Core extraction and OCR dispatch services."""

from __future__ import annotations

import re
from typing import Any

from PIL import Image
from pypdf import PdfReader

from sunshine_extraction.domain.extraction import ExtractionResult, OcrArtifacts, OcrDocumentResult, OcrExecutor, OcrPageResult
from sunshine_extraction.providers.extraction.cortex_ocr import CortexNativeOcrExecutor
from sunshine_extraction.providers.extraction.native_text import extract_text
from sunshine_extraction.providers.extraction.openai_ocr import OCR_FALLBACK_DEFAULT_MAX_PAGES, OpenAIVisionOcrExecutor
from sunshine_extraction.providers.extraction.photo_metadata import extract_photo_metadata
from sunshine_extraction.providers.extraction.spreadsheet import extract_spreadsheet_metadata
from sunshine_extraction.providers.extraction.tesseract_ocr import LocalTesseractOcrExecutor
from sunshine_extraction.services.content import IMAGE_EXTENSIONS, SampleFile
from sunshine_extraction.services.quality.ocr_quality import OCR_MIN_TEXT_LENGTH


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

    from sunshine_extraction.config import DEFAULT_CORTEX_BASE_URL, DEFAULT_CORTEX_OCR_MODEL, DEFAULT_OPENAI_OCR_MODEL

    provider_name = (fallback_provider_override or os.environ.get("SUNSHINE_OCR_FALLBACK_PROVIDER", "cortex")).strip().lower()
    if provider_name in {"", "disabled", "none", "local"}:
        return LocalTesseractOcrExecutor()
    timeout_seconds = float(os.environ.get("SUNSHINE_OCR_FALLBACK_TIMEOUT_SECONDS", "120"))
    max_pages = int(os.environ.get("SUNSHINE_OCR_FALLBACK_MAX_PAGES", str(OCR_FALLBACK_DEFAULT_MAX_PAGES)))
    if provider_name == "openai":
        try:
            fallback = OpenAIVisionOcrExecutor(
                api_key=os.environ.get("SUNSHINE_OCR_FALLBACK_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API", ""),
                model=os.environ.get("SUNSHINE_OCR_FALLBACK_MODEL") or os.environ.get("OPENAI_OCR_MODEL", DEFAULT_OPENAI_OCR_MODEL),
                base_url=os.environ.get("SUNSHINE_OCR_FALLBACK_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1",
                timeout_seconds=timeout_seconds,
                max_pages=max_pages,
            )
        except ValueError:
            return LocalTesseractOcrExecutor()
        return EscalatingOcrExecutor(LocalTesseractOcrExecutor(), fallback)
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


class EscalatingOcrExecutor(OcrExecutor):
    engine_name = "escalating"

    def __init__(self, primary: OcrExecutor, fallback: OcrExecutor) -> None:
        self.primary = primary
        self.fallback = fallback

    def dependency_status(self) -> dict[str, Any]:
        return {
            "engine": "escalating",
            "primary": self.primary.dependency_status(),
            "fallback": self.fallback.dependency_status(),
        }

    def ocr_sample(self, sample: SampleFile, plan: dict[str, Any]) -> tuple[OcrDocumentResult, list[OcrPageResult]]:
        primary_document, primary_pages = self.primary.ocr_sample(sample, plan)
        escalation_reason = _ocr_escalation_reason(primary_document, primary_pages)
        if escalation_reason is None:
            return primary_document, primary_pages

        fallback_document, fallback_pages = self.fallback.ocr_sample(sample, plan)
        primary_text = _shorten(_joined_page_text(primary_pages), 360)
        fallback_text = _shorten(_joined_page_text(fallback_pages), 360)
        fallback_warnings = [
            f"ocr_fallback_used:{self.fallback.engine_name}",
            f"ocr_fallback_reason:{escalation_reason}",
            *([f"ocr_original_snippet:{primary_text}"] if primary_text else []),
            *([f"ocr_fallback_snippet:{fallback_text}"] if fallback_text else []),
            *fallback_document.warnings,
        ]
        return (
            _replace_ocr_document_warnings(fallback_document, fallback_warnings),
            [_with_page_warning(page, f"ocr_fallback_used:{self.fallback.engine_name}") for page in fallback_pages],
        )


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


def _replace_ocr_document_warnings(document: OcrDocumentResult, warnings: list[str]) -> OcrDocumentResult:
    return OcrDocumentResult(
        source_path=document.source_path,
        relative_path=document.relative_path,
        sample_path=document.sample_path,
        ocr_status=document.ocr_status,
        page_count=document.page_count,
        pages_ok=document.pages_ok,
        pages_failed=document.pages_failed,
        total_text_length=document.total_text_length,
        mean_confidence=document.mean_confidence,
        quality=document.quality,
        seconds=document.seconds,
        warnings=sorted(set(warnings)),
    )


def _with_page_warning(page: OcrPageResult, warning: str) -> OcrPageResult:
    return OcrPageResult(
        source_path=page.source_path,
        relative_path=page.relative_path,
        sample_path=page.sample_path,
        page_number=page.page_number,
        page_count=page.page_count,
        ocr_engine=page.ocr_engine,
        ocr_engine_version=page.ocr_engine_version,
        ocr_status=page.ocr_status,
        text=page.text,
        text_length=page.text_length,
        mean_confidence=page.mean_confidence,
        word_count=page.word_count,
        image_width=page.image_width,
        image_height=page.image_height,
        seconds=page.seconds,
        warnings=sorted({*page.warnings, warning}),
    )


def _joined_page_text(pages: list[OcrPageResult]) -> str:
    return "\n\n".join(page.text for page in pages if page.text.strip())


def _ocr_escalation_reason(document: OcrDocumentResult, pages: list[OcrPageResult]) -> str | None:
    if document.quality in {"poor", "metadata_only", "failed", "deferred"}:
        return document.quality
    if _looks_like_gibberish("\n".join(page.text for page in pages)):
        return "gibberish_suspected"
    return None


def _looks_like_gibberish(text: str) -> bool:
    compact = text.strip()
    if len(compact) < OCR_MIN_TEXT_LENGTH:
        return False
    tokens = re.findall(r"[A-Za-z0-9'/$.,:-]+", compact)
    if len(tokens) < 20:
        return False
    odd_character_ratio = len(re.findall(r"[^A-Za-z0-9\s.,:$%/'\"()&+-]", compact)) / max(len(compact), 1)
    alpha_tokens = [token for token in tokens if re.search(r"[A-Za-z]", token)]
    vowel_tokens = [token for token in alpha_tokens if re.search(r"[aeiouAEIOU]", token)]
    vowel_token_ratio = len(vowel_tokens) / max(len(alpha_tokens), 1)
    long_token_ratio = len([token for token in tokens if len(token) > 18]) / len(tokens)
    return odd_character_ratio > 0.3 or (len(alpha_tokens) >= 15 and vowel_token_ratio < 0.2) or long_token_ratio > 0.3


def _shorten(text: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."


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
