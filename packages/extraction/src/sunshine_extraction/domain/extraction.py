"""Extraction and OCR result contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sunshine_extraction.domain.documents import SampleFile


@dataclass(frozen=True)
class ExtractionResult:
    sample: SampleFile
    plan: dict[str, Any]
    extraction_status: str
    text: str
    metadata: dict[str, Any]
    page_count: int | None
    warnings: list[str]


@dataclass(frozen=True)
class OcrPageResult:
    source_path: str
    relative_path: str
    sample_path: str
    page_number: int
    page_count: int
    ocr_engine: str
    ocr_engine_version: str | None
    ocr_status: str
    text: str
    text_length: int
    mean_confidence: float | None
    word_count: int
    image_width: int | None
    image_height: int | None
    seconds: float
    warnings: list[str]

    def as_row(self) -> dict[str, Any]:
        return self.__dict__


@dataclass(frozen=True)
class OcrDocumentResult:
    source_path: str
    relative_path: str
    sample_path: str
    ocr_status: str
    page_count: int
    pages_ok: int
    pages_failed: int
    total_text_length: int
    mean_confidence: float | None
    quality: str
    seconds: float
    warnings: list[str]

    def as_row(self) -> dict[str, Any]:
        return self.__dict__


@dataclass
class OcrArtifacts:
    pages: list[dict[str, Any]]
    documents: list[dict[str, Any]]


class OcrExecutor:
    engine_name = "tesseract"

    def dependency_status(self) -> dict[str, Any]:
        raise NotImplementedError

    def ocr_sample(self, sample: SampleFile, plan: dict[str, Any]) -> tuple[OcrDocumentResult, list[OcrPageResult]]:
        raise NotImplementedError
