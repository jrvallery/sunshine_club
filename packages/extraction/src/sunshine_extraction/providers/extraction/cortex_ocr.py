"""Cortex OCR provider for local OpenAI-compatible infrastructure."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sunshine_extraction.config import DEFAULT_CORTEX_BASE_URL, DEFAULT_CORTEX_OCR_MODEL
from sunshine_extraction.cortex import CortexClient
from sunshine_extraction.domain.extraction import OcrDocumentResult, OcrExecutor, OcrPageResult
from sunshine_extraction.providers.extraction.ocr_common import (
    cortex_ocr_pages,
    cortex_root_base_url,
    failed_ocr_document,
    normalize_ocr_confidence,
    ocr_document_from_pages,
    optional_int,
    shorten,
)
from sunshine_extraction.services.content import SampleFile


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
