"""Tracer-bullet QA sample pipeline.

The functions in this module mirror the intended LangGraph node boundaries but
run as a straightforward Python command for the current milestone.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import mimetypes
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, TextIO

from PIL import ExifTags, Image
from pypdf import PdfReader

from sunshine_extraction.cortex import CortexClient
from sunshine_extraction.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingProvider,
    EmbeddingProviderError,
    PlaceholderEmbeddingProvider,
    embed_texts,
    provider_from_env,
)
from sunshine_extraction.domain.documents import IMAGE_EXTENSIONS, SPREADSHEET_EXTENSIONS, TEXT_EXTENSIONS, SampleFile
from sunshine_extraction.domain.extraction import ExtractionResult, OcrArtifacts, OcrDocumentResult, OcrExecutor, OcrPageResult
from sunshine_extraction.placement import resolve_tag_placement


DEFAULT_MANIFEST_ROOT = Path("/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25")
DEFAULT_INPUT_ROOT = DEFAULT_MANIFEST_ROOT / "qa samples"
DEFAULT_OUTPUT_DIR = DEFAULT_MANIFEST_ROOT / "sample-pipeline"
DEFAULT_CORRECTED_PATH = DEFAULT_MANIFEST_ROOT / "corrected-content-classes.jsonl"
DEFAULT_PLAN_PATH = DEFAULT_MANIFEST_ROOT / "extraction-plan.jsonl"
DEFAULT_TAXONOMY_PATH = Path("docs/Sunshine_Taxonomy_Seed_v0.1_2026-05-25.json")
DEFAULT_CORTEX_BASE_URL = "https://cortex.vallery.net"
DEFAULT_CORTEX_MODEL = "gemma4-26b"
DEFAULT_CORTEX_OCR_MODEL = "paddleocr-ppocr-cpu"
DEFAULT_OPENAI_TAG_MODEL = "disabled-hosted-openai"
DEFAULT_OPENAI_OCR_MODEL = "disabled-hosted-openai"
OCR_OK_CONFIDENCE_THRESHOLD = 75.0
OCR_MIN_TEXT_LENGTH = 100
OCR_MAX_FAILED_PAGE_RATE = 0.2
OCR_FALLBACK_DEFAULT_MAX_PAGES = 25
INITIAL_SAMPLE_LIMITS = {
    "accepted-image-random-100": 10,
    "accepted-scanned-document-random-100": 10,
    "changed-image-to-scanned_document-image_scan_policy_path_or_name": 5,
    "changed-scanned_document-to-document-pdf_extractable_text_detected": 5,
    "changed-document-to-scanned_document-pdf_image_only_or_empty_text": 5,
    "changed-binary_or_unknown-to-spreadsheet-macro_enabled_spreadsheet_review": 1,
}
EXPECTED_STRATEGIES = {
    "ocr_page_level",
    "photo_metadata",
    "text_extraction",
    "spreadsheet_table_extraction",
    "deferred_technical",
}


class LocalTesseractOcrExecutor(OcrExecutor):
    def dependency_status(self) -> dict[str, Any]:
        tesseract_binary = _configure_tesseract_runtime()
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
                pages.append(_ocr_pil_image(sample, image, index, page_count, page_start))
            except Exception as error:  # noqa: BLE001
                pages.append(
                    OcrPageResult(
                        source_path=sample.source_path,
                        relative_path=sample.relative_path,
                        sample_path=str(sample.sample_path),
                        page_number=index,
                        page_count=page_count,
                        ocr_engine="tesseract",
                        ocr_engine_version=_tesseract_version(),
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
        return _ocr_document_from_pages(sample, pages, time.monotonic() - start), pages

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


class OpenAICompatibleVisionOcrExecutor(OcrExecutor):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        provider_name: str = "openai",
        timeout_seconds: float = 120,
        max_pages: int = OCR_FALLBACK_DEFAULT_MAX_PAGES,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required for OCR fallback")
        if not model:
            raise ValueError("model is required for OCR fallback")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/") if base_url else "https://api.openai.com/v1"
        self.provider_name = provider_name
        self.timeout_seconds = timeout_seconds
        self.max_pages = max_pages
        self.engine_name = f"{provider_name}:{model}"

    def dependency_status(self) -> dict[str, Any]:
        return {
            "engine": self.provider_name,
            "model": self.model,
            "base_url": self.base_url,
            "max_pages": self.max_pages,
            "missing": [] if self.api_key else ["api_key"],
        }

    def ocr_sample(self, sample: SampleFile, plan: dict[str, Any]) -> tuple[OcrDocumentResult, list[OcrPageResult]]:
        start = time.monotonic()
        try:
            images = _render_sample_images(sample)
        except Exception as error:  # noqa: BLE001
            return _failed_ocr_document(sample, [f"ocr_fallback_render_failed:{type(error).__name__}"]), []

        warnings: list[str] = []
        if self.max_pages > 0 and len(images) > self.max_pages:
            warnings.append(f"ocr_fallback_page_limit_applied:{self.max_pages}")
            images = images[: self.max_pages]

        pages: list[OcrPageResult] = []
        page_count = len(images)
        for index, image in enumerate(images, start=1):
            page_start = time.monotonic()
            try:
                text, confidence, page_warnings = self._ocr_image(image)
                model_warnings = [f"ocr_model_used:{self.engine_name}", *warnings, *page_warnings]
                pages.append(
                    OcrPageResult(
                        source_path=sample.source_path,
                        relative_path=sample.relative_path,
                        sample_path=str(sample.sample_path),
                        page_number=index,
                        page_count=page_count,
                        ocr_engine=self.engine_name,
                        ocr_engine_version=self.model,
                        ocr_status="ok" if text.strip() else "empty",
                        text=text,
                        text_length=len(text),
                        mean_confidence=round(confidence * 100, 2),
                        word_count=len(text.split()),
                        image_width=image.width,
                        image_height=image.height,
                        seconds=round(time.monotonic() - page_start, 4),
                        warnings=model_warnings,
                    )
                )
            except Exception as error:  # noqa: BLE001
                pages.append(
                    OcrPageResult(
                        source_path=sample.source_path,
                        relative_path=sample.relative_path,
                        sample_path=str(sample.sample_path),
                        page_number=index,
                        page_count=page_count,
                        ocr_engine=self.engine_name,
                        ocr_engine_version=self.model,
                        ocr_status="failed",
                        text="",
                        text_length=0,
                        mean_confidence=None,
                        word_count=0,
                        image_width=image.width,
                        image_height=image.height,
                        seconds=round(time.monotonic() - page_start, 4),
                        warnings=[f"ocr_model_used:{self.engine_name}", *warnings, f"ocr_fallback_page_failed:{type(error).__name__}"],
                    )
                )
            finally:
                image.close()
        return _ocr_document_from_pages(sample, pages, time.monotonic() - start), pages

    def _ocr_image(self, image: Image.Image) -> tuple[str, float, list[str]]:
        prompt = (
            "Transcribe all visible text in this image for archival OCR. Preserve line breaks where useful. "
            "Return only JSON with keys text, confidence, and notes. If no readable text is visible, text must be empty. "
            "Do not summarize, classify, or add facts not visible in the image."
        )
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 4096,
            "messages": [
                {"role": "system", "content": "You are a careful OCR transcription engine. Return only valid JSON."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": _image_to_data_url(image), "detail": "high"}},
                    ],
                },
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        content = response_payload["choices"][0]["message"]["content"]
        parsed = json.loads(_extract_json_object(_message_content_to_text(content)))
        text = str(parsed.get("text") or "").strip()
        confidence = parsed.get("confidence", 0.0)
        if not isinstance(confidence, int | float):
            confidence = 0.0
        raw_notes = parsed.get("notes", [])
        if isinstance(raw_notes, str):
            raw_notes = [raw_notes]
        notes = [str(note) for note in raw_notes if note]
        return text, max(0.0, min(float(confidence), 1.0)), [f"ocr_fallback_note:{_shorten(note, 120)}" for note in notes[:3]]


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
        self.base_url = _cortex_root_base_url(base_url)
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
            return _failed_ocr_document(sample, [f"ocr_fallback_failed:{type(error).__name__}"]), []

        pages_payload = _cortex_ocr_pages(payload)
        if not pages_payload:
            text = str(payload.get("text") or payload.get("output_text") or "").strip()
            pages_payload = [{"page_number": 1, "text": text, "confidence": payload.get("confidence")}]

        page_count = len(pages_payload)
        pages: list[OcrPageResult] = []
        for index, page_payload in enumerate(pages_payload, start=1):
            page_number = int(page_payload.get("page_number") or page_payload.get("page") or index)
            text = str(page_payload.get("text") or page_payload.get("content") or "").strip()
            confidence = _normalize_ocr_confidence(page_payload.get("confidence") or page_payload.get("mean_confidence"))
            warnings = [f"ocr_model_used:{self.engine_name}"]
            notes = page_payload.get("notes")
            if isinstance(notes, str) and notes.strip():
                warnings.append(f"ocr_fallback_note:{_shorten(notes, 120)}")
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
                    image_width=_optional_int(page_payload.get("image_width") or page_payload.get("width")),
                    image_height=_optional_int(page_payload.get("image_height") or page_payload.get("height")),
                    seconds=round(time.monotonic() - start, 4),
                    warnings=warnings,
                )
            )
        return _ocr_document_from_pages(sample, pages, time.monotonic() - start), pages

    def _ocr_file(self, path: Path) -> dict[str, Any]:
        return CortexClient(base_url=self.base_url, api_key=self.api_key, timeout_seconds=self.timeout_seconds).ocr_file(path, model=self.model)


@dataclass(frozen=True)
class TaxonomyOptions:
    primary_tags: list[str]
    secondary_tags: list[str]
    primary_definitions: dict[str, str]


class LLMTagInspector:
    model: str = "disabled"

    def inspect(
        self,
        *,
        sample: SampleFile,
        corrected: dict[str, Any],
        plan: dict[str, Any],
        extraction: ExtractionResult,
        taxonomy: TaxonomyOptions,
        deterministic_candidates: list[dict[str, Any]],
        semantic_examples: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "llm_status": "skipped",
            "model": self.model,
            "provider": "disabled",
            "primary_tag": None,
            "secondary_tags": [],
            "confidence": 0.0,
            "evidence": [],
            "rationale": "LLM tag inspection disabled.",
            "needs_review": False,
            "warning": None,
        }


class OpenAICompatibleLLMTagInspector(LLMTagInspector):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        provider_name: str = "openai-compatible",
        timeout_seconds: float = 120,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required for OpenAI-compatible LLM tag inspection")
        if not model:
            raise ValueError("model is required for OpenAI-compatible LLM tag inspection")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.provider_name = provider_name
        self.timeout_seconds = timeout_seconds
        self._client: Any | None = None

    def inspect(
        self,
        *,
        sample: SampleFile,
        corrected: dict[str, Any],
        plan: dict[str, Any],
        extraction: ExtractionResult,
        taxonomy: TaxonomyOptions,
        deterministic_candidates: list[dict[str, Any]],
        semantic_examples: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        prompt = build_llm_tag_prompt(sample, corrected, plan, extraction, taxonomy, deterministic_candidates, semantic_examples or [])
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            response = self._chat_client().invoke(
                [
                    SystemMessage(
                        content=(
                            "You classify Sunshine Club files. Return only valid JSON matching the requested schema. "
                            "Do not include markdown fences or commentary."
                        )
                    ),
                    HumanMessage(content=prompt),
                ]
            )
            payload = _extract_json_object(_message_content_to_text(response.content))
            inspection = normalize_llm_inspection(json.loads(payload), taxonomy, model=self.model, provider=self.provider_name)
            inspection.update(_chat_response_usage_fields(response))
            return inspection
        except Exception as error:  # noqa: BLE001 - every file needs an auditable failure row.
            return {
                "llm_status": "failed",
                "model": self.model,
                "provider": self.provider_name,
                "primary_tag": None,
                "secondary_tags": [],
                "confidence": 0.0,
                "evidence": [],
                "rationale": "LLM tag inspection failed.",
                "needs_review": True,
                "warning": f"llm_tag_inspection_failed:{type(error).__name__}",
            }

    def _chat_client(self) -> Any:
        if self._client is None:
            from langchain_openai import ChatOpenAI

            kwargs: dict[str, Any] = {
                "model": self.model,
                "api_key": self.api_key,
                "temperature": 0,
                "timeout": self.timeout_seconds,
                "max_retries": 1,
                "max_completion_tokens": 1024,
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = ChatOpenAI(**kwargs)
        return self._client


def run_sample_pipeline(
    input_root: str | Path = DEFAULT_INPUT_ROOT,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    corrected_path: str | Path = DEFAULT_CORRECTED_PATH,
    plan_path: str | Path = DEFAULT_PLAN_PATH,
    taxonomy_path: str | Path = DEFAULT_TAXONOMY_PATH,
    limit: int | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    llm_tag_inspector: LLMTagInspector | None = None,
    ocr_executor: OcrExecutor | None = None,
    progress: bool = False,
) -> dict[str, Any]:
    input_root_path = Path(input_root)
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    _progress(progress, f"sample-pipeline: input_root={input_root_path}")
    _progress(progress, f"sample-pipeline: output_dir={output_dir_path}")
    _progress(progress, "sample-pipeline: loading corrected content classes, extraction plan, and taxonomy")
    corrected_by_key = _load_rows_by_keys(corrected_path)
    plan_by_key = _load_rows_by_keys(plan_path)
    taxonomy = load_taxonomy_options(taxonomy_path)
    samples = select_sample_files(input_root_path)
    if limit is not None:
        samples = samples[:limit]
    _progress(progress, f"sample-pipeline: selected_samples={len(samples)}")

    provider_warnings: list[str] = []
    if embedding_provider is not None:
        provider = embedding_provider
    else:
        try:
            provider = provider_from_env()
        except EmbeddingConfigurationError:
            provider = PlaceholderEmbeddingProvider()
            provider_warnings.append("embedding_provider_configuration_failed_fell_back_to_placeholder")
    _progress(progress, f"sample-pipeline: embedding_provider={provider.__class__.__name__} model={provider.model}")
    artifact_rows: dict[str, list[dict[str, Any]]] = {
        "sample-inputs.jsonl": [],
        "sample-extraction-results.jsonl": [],
        "sample-ocr-pages.jsonl": [],
        "sample-ocr-documents.jsonl": [],
        "sample-chunks.jsonl": [],
        "sample-embeddings.jsonl": [],
        "sample-llm-tag-inspections.jsonl": [],
        "sample-tag-candidates.jsonl": [],
        "sample-pipeline-results.jsonl": [],
    }
    summary_counter: dict[str, Counter[str]] = {
        "by_sample_group": Counter(),
        "by_final_class": Counter(),
        "by_extraction_strategy": Counter(),
        "by_extraction_status": Counter(),
        "by_quality": Counter(),
        "by_ocr_status": Counter(),
        "by_ocr_quality": Counter(),
        "by_chunk_count_bucket": Counter(),
        "by_embedding_status": Counter(),
        "by_llm_status": Counter(),
        "by_top_tag_candidate": Counter(),
        "by_secondary_tag": Counter(),
        "by_route_status": Counter(),
        "by_warning": Counter(),
    }
    inspector = llm_tag_inspector if llm_tag_inspector is not None else llm_tag_inspector_from_env()
    active_ocr_executor = ocr_executor if ocr_executor is not None else LocalTesseractOcrExecutor()
    _progress(progress, f"sample-pipeline: llm_tag_inspector={inspector.__class__.__name__} model={inspector.model}")
    _progress(progress, f"sample-pipeline: ocr_executor={active_ocr_executor.__class__.__name__} status={active_ocr_executor.dependency_status()}")

    for index, sample in enumerate(samples, start=1):
        _progress(progress, f"[{index}/{len(samples)}] start {sample.sample_group} :: {sample.sample_path.name}")
        corrected = load_existing_content_class(sample, corrected_by_key)
        plan = load_existing_extraction_plan(sample, plan_by_key)
        _progress(progress, f"[{index}/{len(samples)}] class={corrected['final_class']} strategy={plan['strategy']} path={sample.relative_path}")
        ocr_artifacts = OcrArtifacts(pages=[], documents=[])
        extraction = extract_content(sample, plan, ocr_executor=active_ocr_executor, ocr_artifacts=ocr_artifacts)
        extraction = validate_and_repair_extraction(
            sample,
            plan,
            extraction,
            ocr_executor=active_ocr_executor,
            ocr_artifacts=ocr_artifacts,
        )
        plan = extraction.plan
        quality = extraction_quality_gate(extraction)
        _progress(
            progress,
            f"[{index}/{len(samples)}] extraction_status={extraction.extraction_status} quality={quality['quality']} warnings={','.join(extraction.warnings) or 'none'}",
        )
        chunks = chunk_content(extraction, quality)
        _progress(progress, f"[{index}/{len(samples)}] chunks={len(chunks)}")
        embeddings, embedding_warnings = embed_chunks_with_fallback(chunks, provider)
        embedding_warnings = [*provider_warnings, *embedding_warnings] if chunks else []
        if embedding_warnings:
            extraction = _with_added_warnings(extraction, embedding_warnings)
        embedding_statuses = sorted({row["embedding_status"] for row in embeddings}) or ["none"]
        _progress(progress, f"[{index}/{len(samples)}] embeddings={len(embeddings)} status={','.join(embedding_statuses)}")
        deterministic_candidates = assign_tag_candidates(sample, corrected, plan, extraction)
        _progress(progress, f"[{index}/{len(samples)}] deterministic_candidates={len(deterministic_candidates)}")
        llm_inspection = inspector.inspect(
            sample=sample,
            corrected=corrected,
            plan=plan,
            extraction=extraction,
            taxonomy=taxonomy,
            deterministic_candidates=deterministic_candidates,
        )
        _progress(
            progress,
            f"[{index}/{len(samples)}] llm_status={llm_inspection.get('llm_status')} llm_primary={llm_inspection.get('primary_tag') or 'none'} llm_confidence={llm_inspection.get('confidence')} llm_warning={llm_inspection.get('warning') or 'none'}",
        )
        tag_candidates = combine_tag_candidates(deterministic_candidates, llm_inspection)
        tag_candidates, confidence_calibration = calibrate_tag_confidence(
            tag_candidates,
            quality,
            plan,
            llm_inspection=llm_inspection,
            semantic_examples=[],
            embeddings=embeddings,
        )
        route = resolve_route_or_review(tag_candidates, quality, plan)
        result = write_pipeline_result(sample, corrected, plan, extraction, quality, chunks, embeddings, tag_candidates, route, llm_inspection, confidence_calibration)
        _progress(
            progress,
            f"[{index}/{len(samples)}] top_tag={result.get('top_tag_candidate') or 'none'} confidence={result.get('tag_confidence')} route={result['route_status']}",
        )

        artifact_rows["sample-inputs.jsonl"].append(sample_input_row(sample, corrected, plan))
        artifact_rows["sample-extraction-results.jsonl"].append(extraction_result_row(extraction, quality))
        artifact_rows["sample-ocr-pages.jsonl"].extend(ocr_artifacts.pages)
        artifact_rows["sample-ocr-documents.jsonl"].extend(ocr_artifacts.documents)
        artifact_rows["sample-chunks.jsonl"].extend(chunks)
        artifact_rows["sample-embeddings.jsonl"].extend(embeddings)
        artifact_rows["sample-llm-tag-inspections.jsonl"].append(llm_inspection_row(sample, llm_inspection))
        artifact_rows["sample-tag-candidates.jsonl"].extend(tag_candidates)
        artifact_rows["sample-pipeline-results.jsonl"].append(result)
        _update_summary_counters(summary_counter, result)

    for filename, rows in artifact_rows.items():
        _write_jsonl(output_dir_path / filename, rows)
        _progress(progress, f"sample-pipeline: wrote {filename} rows={len(rows)}")

    covered_strategies = set(summary_counter["by_extraction_strategy"])
    summary = {
        "input_root": str(input_root_path),
        "output_dir": str(output_dir_path),
        "selected_sample_count": len(samples),
        "artifact_counts": {filename: len(rows) for filename, rows in artifact_rows.items()},
        "missing_expected_strategies": sorted(EXPECTED_STRATEGIES - covered_strategies),
        **{name: dict(sorted(counter.items())) for name, counter in summary_counter.items()},
    }
    (output_dir_path / "sample-pipeline-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    ocr_summary = build_ocr_summary(artifact_rows["sample-ocr-pages.jsonl"], artifact_rows["sample-ocr-documents.jsonl"])
    (output_dir_path / "sample-ocr-summary.json").write_text(
        json.dumps(ocr_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _progress(progress, "sample-pipeline: wrote sample-ocr-summary.json")
    _progress(progress, "sample-pipeline: wrote sample-pipeline-summary.json")
    _progress(progress, "sample-pipeline: complete")
    return summary


def select_sample_files(input_root: Path, limits: dict[str, int] | None = None) -> list[SampleFile]:
    active_limits = limits or INITIAL_SAMPLE_LIMITS
    samples: list[SampleFile] = []
    for group, group_limit in active_limits.items():
        index_path = input_root / group / "index.jsonl"
        if not index_path.exists():
            continue
        for row in _read_jsonl(index_path)[:group_limit]:
            samples.append(
                SampleFile(
                    sample_path=input_root / group / row["link_name"],
                    source_path=row["source_path"],
                    relative_path=row["relative_path"],
                    sample_group=group,
                    sample_number=row.get("number"),
                    index_row=row,
                )
            )
    return samples


def load_existing_content_class(sample: SampleFile, rows_by_key: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return _lookup_by_sample(sample, rows_by_key, artifact_name="corrected content class")


def load_existing_extraction_plan(sample: SampleFile, rows_by_key: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return _lookup_by_sample(sample, rows_by_key, artifact_name="extraction plan")


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
        return _extract_photo_metadata(sample, plan)
    if strategy == "text_extraction":
        return _extract_text(sample, plan)
    if strategy == "spreadsheet_table_extraction":
        return _extract_spreadsheet_metadata(sample, plan)
    if strategy == "ocr_page_level":
        return _extract_ocr_page_level(sample, plan, ocr_executor=ocr_executor, ocr_artifacts=ocr_artifacts)
    return ExtractionResult(sample, plan, "failed", "", {}, None, [f"unsupported_strategy:{strategy}"])


def extraction_quality_gate(extraction: ExtractionResult) -> dict[str, Any]:
    if extraction.extraction_status == "failed":
        return {"quality": "failed", "can_chunk": False, "can_embed": False, "requires_review": True}
    if extraction.extraction_status in {"deferred_technical", "deferred_extractor"}:
        return {
            "quality": "deferred",
            "can_chunk": extraction.extraction_status == "deferred_extractor",
            "can_embed": False,
            "requires_review": True,
        }
    text_validation = extraction.metadata.get("text_validation")
    if isinstance(text_validation, dict) and text_validation.get("status") == "failed":
        return {"quality": "poor", "can_chunk": True, "can_embed": True, "requires_review": True}
    ocr_document = extraction.metadata.get("ocr_document")
    if isinstance(ocr_document, dict) and ocr_document.get("quality") == "poor":
        return {"quality": "poor", "can_chunk": True, "can_embed": True, "requires_review": True}
    if isinstance(ocr_document, dict) and ocr_document.get("quality") == "metadata_only":
        return {"quality": "metadata_only", "can_chunk": True, "can_embed": True, "requires_review": True}
    if extraction.text.strip():
        return {"quality": "ok", "can_chunk": True, "can_embed": True, "requires_review": False}
    if extraction.metadata:
        return {"quality": "metadata_only", "can_chunk": True, "can_embed": True, "requires_review": False}
    return {"quality": "empty", "can_chunk": False, "can_embed": False, "requires_review": True}


def validate_and_repair_extraction(
    sample: SampleFile,
    plan: dict[str, Any],
    extraction: ExtractionResult,
    *,
    ocr_executor: OcrExecutor | None = None,
    ocr_artifacts: OcrArtifacts | None = None,
) -> ExtractionResult:
    validation = validate_extracted_text(extraction)
    if validation["status"] != "failed":
        return _with_text_validation(extraction, validation)

    failed_extraction = _with_text_validation(
        _with_added_warnings(extraction, [f"text_validation_failed:{validation['reason']}"]),
        validation,
    )
    if plan.get("strategy") == "ocr_page_level" or not _can_try_ocr(sample):
        return failed_extraction

    fallback_plan = {
        **plan,
        "strategy": "ocr_page_level",
        "document_subtype": "scanned_or_image_pdf",
        "ocr_required": True,
        "original_strategy": plan.get("strategy"),
    }
    if ocr_executor is None:
        fallback_metadata = {
            "ocr_required": True,
            "document_subtype": fallback_plan.get("document_subtype"),
            "text_validation": {
                "status": "failed",
                "reason": validation["reason"],
                "repair_strategy": "ocr_page_level",
            },
            "original_extraction": {
                "strategy": plan.get("strategy"),
                "status": extraction.extraction_status,
                "text_length": len(extraction.text),
                "text_snippet": _shorten(extraction.text, 360),
                "warnings": extraction.warnings,
            },
        }
        return ExtractionResult(
            sample=sample,
            plan=fallback_plan,
            extraction_status="deferred_extractor",
            text="",
            metadata=fallback_metadata,
            page_count=extraction.page_count,
            warnings=[
                *extraction.warnings,
                f"text_validation_failed:{validation['reason']}",
                f"text_extraction_fallback_to_ocr:{plan.get('strategy')}",
                "ocr_executor_not_provided",
            ],
        )
    fallback = _extract_ocr_page_level(
        sample,
        fallback_plan,
        ocr_executor=ocr_executor,
        ocr_artifacts=ocr_artifacts,
    )
    fallback_metadata = {
        **fallback.metadata,
        "text_validation": {"status": "repaired", "reason": validation["reason"], "repair_strategy": "ocr_page_level"},
        "original_extraction": {
            "strategy": plan.get("strategy"),
            "status": extraction.extraction_status,
            "text_length": len(extraction.text),
            "text_snippet": _shorten(extraction.text, 360),
            "warnings": extraction.warnings,
        },
    }
    return ExtractionResult(
        sample=sample,
        plan=fallback_plan,
        extraction_status=fallback.extraction_status,
        text=fallback.text,
        metadata=fallback_metadata,
        page_count=fallback.page_count,
        warnings=[
            *extraction.warnings,
            f"text_validation_failed:{validation['reason']}",
            f"text_extraction_fallback_to_ocr:{plan.get('strategy')}",
            *fallback.warnings,
        ],
    )


def validate_extracted_text(extraction: ExtractionResult) -> dict[str, Any]:
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


def chunk_content(extraction: ExtractionResult, quality: dict[str, Any], *, chunk_size: int = 1800) -> list[dict[str, Any]]:
    if not quality["can_chunk"]:
        return []
    if extraction.text.strip():
        chunks = []
        text = extraction.text.strip()
        for index, start in enumerate(range(0, len(text), chunk_size), start=1):
            chunk_text = text[start : start + chunk_size]
            chunks.append(_chunk_row(extraction, index, "text", chunk_text, {"char_start": start, "char_end": start + len(chunk_text)}))
        return chunks

    metadata_text = json.dumps(extraction.metadata, sort_keys=True)
    if extraction.extraction_status == "deferred_extractor":
        metadata_text = f"OCR deferred for {extraction.sample.relative_path}. Metadata: {metadata_text}"
    return [_chunk_row(extraction, 1, "metadata", metadata_text, extraction.metadata)]


def embed_chunks(chunks: list[dict[str, Any]], provider: EmbeddingProvider) -> list[dict[str, Any]]:
    if not chunks:
        return []
    results = embed_texts([chunk["text"] for chunk in chunks], provider)
    rows = []
    for chunk, result in zip(chunks, results, strict=True):
        row = result.as_row()
        row.update({"source_path": chunk["source_path"], "relative_path": chunk["relative_path"], "chunk_id": chunk["chunk_id"]})
        rows.append(row)
    return rows


def embed_chunks_with_fallback(chunks: list[dict[str, Any]], provider: EmbeddingProvider) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        return embed_chunks(chunks, provider), []
    except (EmbeddingConfigurationError, EmbeddingProviderError):
        return embed_chunks(chunks, PlaceholderEmbeddingProvider()), ["embedding_provider_failed_fell_back_to_placeholder"]


def load_pipeline_env(env_path: str | Path | None = ".env") -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
    except Exception:  # noqa: BLE001 - .env support is best-effort for CLI convenience.
        pass

    cortex_api = os.environ.get("CORTEX_API_KEY")
    if cortex_api and not os.environ.get("CORTEX_OPENAI_API_KEY"):
        os.environ["CORTEX_OPENAI_API_KEY"] = cortex_api
    cortex_base = os.environ.get("CORTEX_BASE_URL")
    if cortex_base and not os.environ.get("CORTEX_OPENAI_BASE_URL"):
        os.environ["CORTEX_OPENAI_BASE_URL"] = _cortex_openai_base_url(cortex_base)


def llm_tag_inspector_from_env(*, enabled: bool = True, provider_override: str | None = None) -> LLMTagInspector:
    if not enabled:
        return LLMTagInspector()

    provider_name = (provider_override or os.environ.get("SUNSHINE_LLM_TAG_PROVIDER", "")).strip().lower()
    if provider_name in {"", "disabled", "none"}:
        return LLMTagInspector()
    if provider_name == "auto":
        if os.environ.get("CORTEX_API_KEY") or os.environ.get("CORTEX_OPENAI_API_KEY") or os.environ.get("CORTEX_MODEL"):
            provider_name = "cortex"
        else:
            return LLMTagInspector()
    if provider_name in {"cortex", "openai-compatible"}:
        try:
            return OpenAICompatibleLLMTagInspector(
                api_key=os.environ.get("CORTEX_API_KEY") or os.environ.get("CORTEX_OPENAI_API_KEY", ""),
                model=os.environ.get("CORTEX_MODEL", DEFAULT_CORTEX_MODEL),
                base_url=os.environ.get("CORTEX_OPENAI_BASE_URL") or _cortex_openai_base_url(os.environ.get("CORTEX_BASE_URL", DEFAULT_CORTEX_BASE_URL)),
                provider_name="cortex",
                timeout_seconds=float(os.environ.get("SUNSHINE_LLM_TAG_TIMEOUT_SECONDS", "120")),
            )
        except ValueError:
            return LLMTagInspector()
    if provider_name == "openai":
        return LLMTagInspector()
    return LLMTagInspector()


def ocr_executor_from_env(*, fallback_provider_override: str | None = None) -> OcrExecutor:
    provider_name = (fallback_provider_override or os.environ.get("SUNSHINE_OCR_FALLBACK_PROVIDER", "cortex")).strip().lower()
    if provider_name in {"", "disabled", "none", "local"}:
        return LocalTesseractOcrExecutor()
    timeout_seconds = float(os.environ.get("SUNSHINE_OCR_FALLBACK_TIMEOUT_SECONDS", "120"))
    max_pages = int(os.environ.get("SUNSHINE_OCR_FALLBACK_MAX_PAGES", str(OCR_FALLBACK_DEFAULT_MAX_PAGES)))
    if provider_name == "openai":
        return LocalTesseractOcrExecutor()
    if provider_name in {"cortex", "openai-compatible"}:
        try:
            primary = CortexNativeOcrExecutor(
                api_key=os.environ.get("SUNSHINE_OCR_FALLBACK_API_KEY") or os.environ.get("CORTEX_API_KEY") or os.environ.get("CORTEX_OPENAI_API_KEY", ""),
                model=os.environ.get("SUNSHINE_OCR_FALLBACK_MODEL") or os.environ.get("CORTEX_OCR_MODEL", DEFAULT_CORTEX_OCR_MODEL),
                base_url=os.environ.get("SUNSHINE_OCR_FALLBACK_BASE_URL") or os.environ.get("CORTEX_BASE_URL", DEFAULT_CORTEX_BASE_URL),
                timeout_seconds=timeout_seconds,
            )
        except ValueError:
            return LocalTesseractOcrExecutor()
        return primary
    return LocalTesseractOcrExecutor()


def load_taxonomy_options(path: str | Path) -> TaxonomyOptions:
    taxonomy_path = Path(path)
    if not taxonomy_path.is_absolute():
        taxonomy_path = Path.cwd() / taxonomy_path
    payload = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    primary_tags = [row["tag_key"] for row in payload.get("primary_tags", []) if row.get("tag_key")]
    primary_definitions = {
        row["tag_key"]: row.get("definition", "")
        for row in payload.get("primary_tags", [])
        if row.get("tag_key")
    }
    secondary_tags: list[str] = []
    for section in ("record_types", "functions", "usage_tags"):
        secondary_tags.extend(row["key"] for row in payload.get(section, []) if row.get("key"))
    return TaxonomyOptions(
        primary_tags=primary_tags,
        secondary_tags=sorted(dict.fromkeys(secondary_tags)),
        primary_definitions=primary_definitions,
    )


def build_llm_tag_prompt(
    sample: SampleFile,
    corrected: dict[str, Any],
    plan: dict[str, Any],
    extraction: ExtractionResult,
    taxonomy: TaxonomyOptions,
    deterministic_candidates: list[dict[str, Any]],
    semantic_examples: list[dict[str, Any]] | None = None,
) -> str:
    primary_lines = "\n".join(
        f"- {tag}: {taxonomy.primary_definitions.get(tag, '')}"
        for tag in taxonomy.primary_tags
    )
    context = {
        "relative_path": sample.relative_path,
        "filename": sample.sample_path.name,
        "final_class": corrected.get("final_class"),
        "document_subtype": plan.get("document_subtype"),
        "extraction_strategy": plan.get("strategy"),
        "extraction_status": extraction.extraction_status,
        "metadata": extraction.metadata,
        "deterministic_candidates": deterministic_candidates[:5],
        "nearest_human_labeled_examples": (semantic_examples or [])[:5],
        "text_excerpt": extraction.text[:3500],
    }
    return (
        "Classify this Sunshine Club file for routing and retrieval.\n"
        "Choose exactly one primary_tag from the allowed primary tags. Choose zero to five secondary_tags "
        "from the allowed secondary tags. Base the decision only on the provided path, metadata, text excerpt, "
        "deterministic candidates, and nearest human-labeled examples. Treat human-labeled examples as precedent, "
        "but do not copy them when the current file evidence differs. If evidence is weak or examples conflict, "
        "lower confidence and set needs_review=true.\n\n"
        "Return only a JSON object with these keys: primary_tag, secondary_tags, confidence, evidence, competing_tags, "
        "rationale, needs_review, review_reason. competing_tags must be zero to three alternate primary tag keys. "
        "When needs_review is true, review_reason must briefly explain why. Do not include markdown or any text outside the JSON object.\n\n"
        f"Allowed primary tags:\n{primary_lines}\n\n"
        f"Allowed secondary tags:\n{', '.join(taxonomy.secondary_tags)}\n\n"
        f"File context JSON:\n{json.dumps(context, sort_keys=True)}"
    )


def llm_tag_schema(taxonomy: TaxonomyOptions) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "primary_tag": {"type": "string", "enum": taxonomy.primary_tags},
            "secondary_tags": {
                "type": "array",
                "items": {"type": "string", "enum": taxonomy.secondary_tags},
                "maxItems": 5,
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            "competing_tags": {
                "type": "array",
                "items": {"type": "string", "enum": taxonomy.primary_tags},
                "maxItems": 3,
            },
            "rationale": {"type": "string"},
            "needs_review": {"type": "boolean"},
            "review_reason": {"type": "string"},
        },
        "required": ["primary_tag", "secondary_tags", "confidence", "evidence", "competing_tags", "rationale", "needs_review", "review_reason"],
    }


def normalize_llm_inspection(payload: dict[str, Any], taxonomy: TaxonomyOptions, *, model: str, provider: str = "unknown") -> dict[str, Any]:
    primary_tag = payload.get("primary_tag")
    if primary_tag not in taxonomy.primary_tags:
        primary_tag = None
    raw_secondary_tags = [tag for tag in payload.get("secondary_tags", []) if isinstance(tag, str)]
    invalid_secondary_tags = [tag for tag in raw_secondary_tags if tag not in taxonomy.secondary_tags]
    secondary_tags = [tag for tag in raw_secondary_tags if tag in taxonomy.secondary_tags][:5]
    confidence = payload.get("confidence", 0)
    if not isinstance(confidence, int | float):
        confidence = 0
    evidence = [str(item) for item in payload.get("evidence", [])[:5]]
    raw_competing_tags = [tag for tag in payload.get("competing_tags", []) if isinstance(tag, str)]
    invalid_competing_tags = [tag for tag in raw_competing_tags if tag not in taxonomy.primary_tags]
    competing_tags = [tag for tag in raw_competing_tags if tag in taxonomy.primary_tags and tag != primary_tag][:3]
    needs_review = bool(payload.get("needs_review", False))
    review_reason = str(payload.get("review_reason") or "").strip()
    warnings: list[str] = []
    if primary_tag is None:
        review_reason = review_reason or "llm_primary_tag_invalid"
        warnings.append("llm_primary_tag_invalid")
    elif needs_review:
        review_reason = review_reason or "llm_requested_review"
    if invalid_secondary_tags:
        warnings.append(f"llm_invalid_secondary_tags:{','.join(invalid_secondary_tags[:5])}")
    if invalid_competing_tags:
        warnings.append(f"llm_invalid_competing_tags:{','.join(invalid_competing_tags[:5])}")
    llm_status = "inspected"
    if primary_tag is None:
        llm_status = "invalid"
    elif warnings:
        llm_status = "inspected_with_invalid_fields"
    return {
        "llm_status": llm_status,
        "model": model,
        "provider": provider,
        "primary_tag": primary_tag,
        "secondary_tags": secondary_tags,
        "invalid_secondary_tags": invalid_secondary_tags[:5],
        "confidence": max(0.0, min(float(confidence), 1.0)),
        "evidence": evidence,
        "competing_tags": competing_tags,
        "invalid_competing_tags": invalid_competing_tags[:5],
        "rationale": str(payload.get("rationale", "")),
        "needs_review": needs_review,
        "review_reason": review_reason or None,
        "warnings": warnings,
        "warning": warnings[0] if warnings else None,
    }


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content)


def _chat_response_usage_fields(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage_metadata", None)
    if not isinstance(usage, dict):
        metadata = getattr(response, "response_metadata", None)
        if isinstance(metadata, dict):
            usage = metadata.get("token_usage") or metadata.get("usage")
    if not isinstance(usage, dict):
        return {}
    prompt_tokens = _optional_positive_int(usage.get("input_tokens") or usage.get("prompt_tokens"))
    output_tokens = _optional_positive_int(usage.get("output_tokens") or usage.get("completion_tokens"))
    total_tokens = _optional_positive_int(usage.get("total_tokens"))
    fields: dict[str, int] = {}
    if prompt_tokens is not None:
        fields["input_tokens"] = prompt_tokens
    if output_tokens is not None:
        fields["output_tokens"] = output_tokens
    if total_tokens is not None:
        fields["total_tokens"] = total_tokens
    elif prompt_tokens is not None or output_tokens is not None:
        fields["total_tokens"] = int(prompt_tokens or 0) + int(output_tokens or 0)
    return fields


def _optional_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float) and value >= 0:
        return int(value)
    return None


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise json.JSONDecodeError("No JSON object found in LLM response", stripped, 0)
    return stripped[start : end + 1]


def assign_tag_candidates(sample: SampleFile, corrected: dict[str, Any], plan: dict[str, Any], extraction: ExtractionResult) -> list[dict[str, Any]]:
    if plan["strategy"] == "deferred_technical":
        return []

    haystack = " ".join(
        [
            sample.relative_path,
            sample.sample_path.name,
            str(plan.get("document_subtype") or ""),
            extraction.text[:4000],
            json.dumps(extraction.metadata, sort_keys=True),
            str(corrected.get("review_notes") or ""),
        ]
    ).lower()
    rules = [
        (
            "history_archive_general",
            0.93,
            ["founders of sunshine club", "organized in 1902", "purpose of the sunshine club", "membership has grown", "charitable projects"],
            "historical club summary evidence",
            ["history_archive", "programs_mission"],
        ),
        ("scrapbooks", 0.92, ["scrapbook"], "scrapbook evidence", []),
        ("press_publications", 0.9, ["newspaper", "article", "profile", "ledger", "clipping", "obituary"], "press/profile evidence", []),
        ("annual_spring_tea", 0.88, ["sunshine tea invitation", "tea guest list", "tea program", "/teas/", "teas/", "_tea", "guest list"], "tea/guest-list evidence", []),
        ("meeting_records", 0.87, ["meeting", "minutes", "agenda"], "meeting/minutes evidence", []),
        ("dental_program", 0.87, ["dental", "dentist", "clinic"], "dental evidence", []),
        ("finance_treasurer_records", 0.86, ["treasurer", "paypal", "receipt", "budget", "financial"], "finance evidence", []),
        ("legal_insurance_compliance", 0.86, ["incorporation", "legal", "insurance", "policy", "501c3"], "legal/insurance evidence", []),
        ("historical_photos", 0.8, ["photo", "photograph", "img_", "fastfoto", ".jpg", ".jpeg", ".png"], "photo/history evidence", []),
        ("history_archive_general", 0.65, ["history", "archive", "sunshine"], "history/archive fallback evidence", []),
    ]
    candidates = []
    for tag, confidence, needles, explanation, secondary_tags in rules:
        matches = [needle for needle in needles if needle in haystack]
        if matches:
            candidates.append(
                {
                    "source_path": sample.source_path,
                    "relative_path": sample.relative_path,
                    "tag": tag,
                    "confidence": confidence,
                    "evidence": [explanation, *[f"matched:{match.strip()}" for match in matches[:3]]],
                    "secondary_tags": secondary_tags,
                    "assignment_source": "deterministic",
                }
            )
    candidates.sort(key=lambda row: row["confidence"], reverse=True)
    deduped: list[dict[str, Any]] = []
    seen_tags: set[str] = set()
    for candidate in candidates:
        if candidate["tag"] in seen_tags:
            continue
        deduped.append(candidate)
        seen_tags.add(candidate["tag"])
    return deduped[:5]


def combine_tag_candidates(
    deterministic_candidates: list[dict[str, Any]],
    llm_inspection: dict[str, Any],
    semantic_examples: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not _llm_inspection_has_usable_primary(llm_inspection):
        return _apply_semantic_example_adjustments(deterministic_candidates, semantic_examples or [])

    primary_tag = llm_inspection["primary_tag"]
    llm_confidence = float(llm_inspection.get("confidence") or 0)
    combined = [dict(candidate) for candidate in deterministic_candidates]
    matched = False
    for candidate in combined:
        if candidate["tag"] == primary_tag:
            matched = True
            candidate["confidence"] = min(0.99, (candidate["confidence"] * 0.65) + (llm_confidence * 0.35) + 0.08)
            candidate["evidence"] = [
                *candidate.get("evidence", []),
                "llm_agreed_with_deterministic_primary",
                *[f"llm:{item}" for item in llm_inspection.get("evidence", [])[:2]],
            ]
            candidate["secondary_tags"] = llm_inspection.get("secondary_tags", [])
            candidate["assignment_source"] = "deterministic+llm"
            break
    if not matched:
        combined.append(
            {
                "source_path": deterministic_candidates[0]["source_path"] if deterministic_candidates else None,
                "relative_path": deterministic_candidates[0]["relative_path"] if deterministic_candidates else None,
                "tag": primary_tag,
                "confidence": min(0.82, llm_confidence * 0.85),
                "evidence": ["llm_primary_without_deterministic_agreement", *[f"llm:{item}" for item in llm_inspection.get("evidence", [])[:3]]],
                "secondary_tags": llm_inspection.get("secondary_tags", []),
                "assignment_source": "llm",
            }
        )
    combined.sort(key=lambda row: row["confidence"], reverse=True)
    return _apply_semantic_example_adjustments(combined, semantic_examples or [])[:5]


def _llm_inspection_has_usable_primary(llm_inspection: dict[str, Any]) -> bool:
    return llm_inspection.get("llm_status") in {"inspected", "inspected_with_invalid_fields"} and bool(llm_inspection.get("primary_tag"))


def _apply_semantic_example_adjustments(candidates: list[dict[str, Any]], semantic_examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not semantic_examples:
        return candidates
    adjusted = [dict(candidate) for candidate in candidates]
    top_examples = semantic_examples[:5]
    for candidate in adjusted:
        tag = candidate.get("tag")
        matching_examples = [example for example in top_examples if example.get("correct_primary_tag") == tag]
        conflicting_examples = [example for example in top_examples[:3] if example.get("correct_primary_tag") != tag]
        evidence = list(candidate.get("evidence", []))
        if matching_examples:
            best_score = max(float(example.get("score") or 0) for example in matching_examples)
            candidate["confidence"] = min(0.99, float(candidate.get("confidence") or 0) + min(0.06, max(0.0, best_score) * 0.06))
            evidence.append(f"semantic_example_agreement:{tag}:{best_score:.3f}")
            source = str(candidate.get("assignment_source") or "")
            candidate["assignment_source"] = f"{source}+semantic" if source and "semantic" not in source else source or "semantic"
        elif conflicting_examples:
            best_conflict = max(float(example.get("score") or 0) for example in conflicting_examples)
            if best_conflict >= 0.65:
                candidate["confidence"] = max(0.0, float(candidate.get("confidence") or 0) - min(0.05, best_conflict * 0.05))
                evidence.append(f"semantic_example_conflict:{conflicting_examples[0].get('correct_primary_tag')}:{best_conflict:.3f}")
        candidate["evidence"] = evidence

    existing_tags = {candidate.get("tag") for candidate in adjusted}
    for example in top_examples[:3]:
        example_tag = example.get("correct_primary_tag")
        score = float(example.get("score") or 0)
        if example_tag and example_tag not in existing_tags and score >= 0.7:
            adjusted.append(
                {
                    "source_path": None,
                    "relative_path": None,
                    "tag": example_tag,
                    "confidence": min(0.78, score * 0.72),
                    "evidence": [f"semantic_example_only:{example_tag}:{score:.3f}", str(example.get("relative_path") or "")],
                    "secondary_tags": example.get("correct_secondary_tags", []),
                    "assignment_source": "semantic",
                }
            )
            existing_tags.add(example_tag)
    adjusted.sort(key=lambda row: row["confidence"], reverse=True)
    return adjusted


def calibrate_tag_confidence(
    tag_candidates: list[dict[str, Any]],
    quality: dict[str, Any],
    plan: dict[str, Any],
    *,
    llm_inspection: dict[str, Any] | None = None,
    semantic_examples: list[dict[str, Any]] | None = None,
    embeddings: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not tag_candidates:
        return [], {
            "status": "no_candidates",
            "base_confidence": None,
            "calibrated_confidence": None,
            "factors": ["no_tag_candidates"],
            "requires_review": True,
            "review_reason": "no_tag_candidate",
        }

    calibrated = [dict(candidate) for candidate in tag_candidates]
    top = calibrated[0]
    base_confidence = float(top.get("confidence") or 0)
    confidence = base_confidence
    factors: list[str] = []
    requires_review = False
    review_reason: str | None = None

    quality_value = str(quality.get("quality") or "unknown")
    if quality.get("requires_review") or quality_value in {"poor", "failed", "deferred", "empty"}:
        confidence = min(confidence, 0.74)
        factors.append(f"extraction_quality_requires_review:{quality_value}")
        requires_review = True
        review_reason = "extraction_quality_not_trusted"

    if plan.get("strategy") == "ocr_page_level" and quality_value == "metadata_only":
        confidence = min(confidence, 0.79)
        factors.append("ocr_metadata_only")
        requires_review = True
        review_reason = "ocr_text_empty"

    llm = llm_inspection or {}
    llm_primary = llm.get("primary_tag")
    llm_confidence = float(llm.get("confidence") or 0)
    if llm.get("needs_review"):
        confidence = min(confidence, 0.79)
        factors.append("llm_requested_review")
        requires_review = True
        review_reason = "llm_requested_review"
    if llm.get("llm_status") in {"failed", "invalid"}:
        confidence = min(confidence, 0.79)
        factors.append(f"llm_structured_output_unusable:{llm.get('llm_status')}")
        requires_review = True
        review_reason = llm.get("review_reason") or "llm_structured_output_unusable"
    elif llm.get("llm_status") == "inspected_with_invalid_fields" or _llm_warning_list(llm):
        confidence = min(confidence, 0.79)
        factors.append("llm_structured_output_invalid_fields")
        requires_review = True
        review_reason = "llm_structured_output_invalid"
    if llm.get("llm_status") == "inspected" and llm_primary and llm_primary != top.get("tag") and llm_confidence >= 0.7:
        confidence = min(confidence, 0.78)
        factors.append(f"llm_primary_disagrees:{llm_primary}")
        requires_review = True
        review_reason = "llm_tag_disagreement"

    top_examples = (semantic_examples or [])[:3]
    if top_examples:
        matching = [example for example in top_examples if example.get("correct_primary_tag") == top.get("tag")]
        conflicting = [example for example in top_examples if example.get("correct_primary_tag") != top.get("tag")]
        strong_conflict = [example for example in conflicting if float(example.get("score") or 0) >= 0.72]
        if matching:
            factors.append(f"semantic_support:{len(matching)}")
        if strong_conflict and len(strong_conflict) >= len(matching):
            best = strong_conflict[0]
            confidence = min(confidence, 0.8)
            factors.append(f"semantic_conflict:{best.get('correct_primary_tag')}:{float(best.get('score') or 0):.3f}")
            requires_review = True
            review_reason = "semantic_example_conflict"

    embedding_statuses = {str(row.get("embedding_status") or "") for row in (embeddings or [])}
    if "placeholder" in embedding_statuses:
        factors.append("embedding_placeholder_used")

    confidence = round(max(0.0, min(confidence, 0.99)), 4)
    top["pre_calibration_confidence"] = base_confidence
    top["confidence"] = confidence
    top["confidence_calibration_factors"] = factors
    top["requires_review"] = requires_review
    top["calibrated_review_reason"] = review_reason
    top["evidence"] = [
        *top.get("evidence", []),
        *[f"confidence_calibration:{factor}" for factor in factors],
    ]
    calibrated[0] = top
    return calibrated, {
        "status": "calibrated",
        "base_confidence": base_confidence,
        "calibrated_confidence": confidence,
        "factors": factors,
        "requires_review": requires_review,
        "review_reason": review_reason,
        "top_tag": top.get("tag"),
    }


def resolve_route_or_review(tag_candidates: list[dict[str, Any]], quality: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    if plan["strategy"] == "deferred_technical":
        return {"route_status": "technical_followup", "review_reason": plan.get("defer_reason")}
    if quality["quality"] == "deferred":
        return {"route_status": "review_or_extraction_deferred", "review_reason": "extractor_deferred"}
    if quality["quality"] == "failed":
        return {"route_status": "review_failed_extraction", "review_reason": "extraction_failed"}
    if quality["quality"] == "poor":
        if plan.get("strategy") != "ocr_page_level":
            return {"route_status": "review_text_quality", "review_reason": "text_quality_not_trusted"}
        return {"route_status": "review_ocr_quality", "review_reason": "ocr_quality_not_trusted"}
    if plan["strategy"] == "ocr_page_level" and quality["quality"] == "metadata_only":
        return {"route_status": "review_ocr_no_text", "review_reason": "ocr_text_empty"}
    if not tag_candidates:
        return {"route_status": "review_no_tag_candidate", "review_reason": "no_tag_candidate"}

    top = tag_candidates[0]
    if top.get("requires_review"):
        return {"route_status": "review_tag_confidence_calibration", "review_reason": top.get("calibrated_review_reason") or "confidence_calibration_requires_review"}
    if top["confidence"] >= 0.85:
        return {"route_status": "route_candidate", "review_reason": None}
    if quality["quality"] == "metadata_only" and top["confidence"] >= 0.8:
        return {"route_status": "route_candidate", "review_reason": None}
    return {"route_status": "review_low_confidence_tag", "review_reason": "tag_confidence_below_threshold"}


def write_pipeline_result(
    sample: SampleFile,
    corrected: dict[str, Any],
    plan: dict[str, Any],
    extraction: ExtractionResult,
    quality: dict[str, Any],
    chunks: list[dict[str, Any]],
    embeddings: list[dict[str, Any]],
    tag_candidates: list[dict[str, Any]],
    route: dict[str, Any],
    llm_inspection: dict[str, Any],
    confidence_calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    top = tag_candidates[0] if tag_candidates else None
    embedding_statuses = sorted({row["embedding_status"] for row in embeddings})
    placement = resolve_tag_placement(
        top["tag"] if top else None,
        relative_path=sample.relative_path,
        source_path=sample.source_path,
        filename=sample.sample_path.name,
        text=extraction.text,
        metadata=extraction.metadata,
    )
    placement = quarantine_placement_for_review_route(placement, route)
    return {
        "sample_path": str(sample.sample_path),
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
        "sample_group": sample.sample_group,
        "final_class": corrected["final_class"],
        "document_subtype": plan.get("document_subtype"),
        "extraction_strategy": plan["strategy"],
        "extraction_status": extraction.extraction_status,
        "quality": quality["quality"],
        "ocr_status": extraction.metadata.get("ocr_document", {}).get("ocr_status") if isinstance(extraction.metadata.get("ocr_document"), dict) else None,
        "ocr_mean_confidence": extraction.metadata.get("ocr_document", {}).get("mean_confidence") if isinstance(extraction.metadata.get("ocr_document"), dict) else None,
        "chunk_count": len(chunks),
        "embedding_status": ",".join(embedding_statuses) if embedding_statuses else "none",
        "top_tag_candidate": top["tag"] if top else None,
        "tag_confidence": top["confidence"] if top else None,
        "tag_evidence": top["evidence"] if top else [],
        "competing_tags": tag_candidates[1:5],
        "secondary_tags": top.get("secondary_tags", []) if top else [],
        "tag_assignment_source": top.get("assignment_source") if top else None,
        "placement": placement,
        "destination_path": placement.get("destination_path"),
        "placement_status": placement.get("placement_status"),
        "placement_rule": placement.get("placement_rule"),
        "placement_date_confidence": placement.get("date_confidence"),
        "default_privacy": placement.get("default_privacy"),
        "reviewer_role": placement.get("reviewer_role"),
        "llm_status": llm_inspection.get("llm_status"),
        "llm_provider": llm_inspection.get("provider"),
        "llm_primary_tag": llm_inspection.get("primary_tag"),
        "llm_confidence": llm_inspection.get("confidence"),
        "llm_competing_tags": llm_inspection.get("competing_tags", []),
        "llm_review_reason": llm_inspection.get("review_reason"),
        "llm_warnings": _llm_warning_list(llm_inspection),
        "confidence_inputs": {
            "top_candidate": top if top else None,
            "candidate_count": len(tag_candidates),
            "llm_confidence": llm_inspection.get("confidence"),
            "llm_needs_review": llm_inspection.get("needs_review"),
            "llm_competing_tags": llm_inspection.get("competing_tags", []),
            "llm_review_reason": llm_inspection.get("review_reason"),
        },
        "confidence_calibration": confidence_calibration or {},
        "ocr_evidence": _ocr_evidence(extraction),
        "route_status": route["route_status"],
        "review_reason": route.get("review_reason"),
        "warnings": [*extraction.warnings, *_llm_warning_list(llm_inspection)],
    }


def _llm_warning_list(llm_inspection: dict[str, Any]) -> list[str]:
    warnings = [str(warning) for warning in llm_inspection.get("warnings", []) if warning]
    if llm_inspection.get("warning"):
        warnings.append(str(llm_inspection["warning"]))
    return sorted(dict.fromkeys(warnings))


def quarantine_placement_for_review_route(placement: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    if route.get("route_status") == "route_candidate":
        return placement
    if placement.get("placement_status") != "resolved":
        return placement
    destination_path = str(placement.get("destination_path") or "")
    if not destination_path or destination_path.startswith("90_Intake_Needs_Review"):
        return placement
    drive_folder = str(placement.get("drive_folder") or "").strip("/")
    review_destination = f"90_Intake_Needs_Review/{drive_folder}" if drive_folder else "90_Intake_Needs_Review"
    return {
        **placement,
        "placement_status": "needs_review",
        "destination_path": review_destination,
        "blocked_destination_path": destination_path,
        "placement_blocked_by_route": True,
        "review_reason": route.get("review_reason") or "placement_requires_accepted_route",
    }


def llm_inspection_row(sample: SampleFile, inspection: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_path": str(sample.sample_path),
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
        **inspection,
    }


def sample_input_row(sample: SampleFile, corrected: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_path": str(sample.sample_path),
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
        "sample_group": sample.sample_group,
        "sample_number": sample.sample_number,
        "final_class": corrected["final_class"],
        "final_status": corrected["final_status"],
        "extraction_strategy": plan["strategy"],
    }


def extraction_result_row(extraction: ExtractionResult, quality: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_path": str(extraction.sample.sample_path),
        "source_path": extraction.sample.source_path,
        "relative_path": extraction.sample.relative_path,
        "extraction_strategy": extraction.plan["strategy"],
        "extraction_status": extraction.extraction_status,
        "quality": quality["quality"],
        "text": extraction.text,
        "metadata": extraction.metadata,
        "page_count": extraction.page_count,
        "warnings": extraction.warnings,
    }


def _extract_text(sample: SampleFile, plan: dict[str, Any]) -> ExtractionResult:
    suffix = sample.sample_path.suffix.lower()
    try:
        if suffix == ".pdf":
            reader = PdfReader(str(sample.sample_path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return ExtractionResult(
                sample,
                plan,
                "extracted",
                text,
                {"mime_type": "application/pdf"},
                len(reader.pages),
                [] if text.strip() else ["pdf_text_empty"],
            )
        if suffix in TEXT_EXTENSIONS:
            return ExtractionResult(
                sample,
                plan,
                "extracted",
                sample.sample_path.read_text(encoding="utf-8", errors="replace"),
                {"mime_type": mimetypes.guess_type(sample.sample_path.name)[0]},
                None,
                [],
            )
    except Exception as error:  # noqa: BLE001 - artifact must capture failures per file.
        return ExtractionResult(sample, plan, "failed", "", {"error": str(error)}, None, ["text_extraction_failed"])

    return ExtractionResult(sample, plan, "deferred_extractor", "", {"suffix": suffix}, None, ["document_executor_not_installed"])


def _extract_photo_metadata(sample: SampleFile, plan: dict[str, Any]) -> ExtractionResult:
    try:
        with Image.open(sample.sample_path) as image:
            exif = image.getexif()
            captured_at = None
            if exif:
                exif_by_name = {ExifTags.TAGS.get(key, str(key)): value for key, value in exif.items()}
                captured_at = exif_by_name.get("DateTimeOriginal") or exif_by_name.get("DateTime")
            metadata = {
                "image_format": image.format,
                "width": image.width,
                "height": image.height,
                "mode": image.mode,
                "frame_count": getattr(image, "n_frames", 1),
                "captured_at": captured_at,
            }
        return ExtractionResult(sample, plan, "metadata_extracted", "", metadata, None, [])
    except Exception as error:  # noqa: BLE001
        return ExtractionResult(sample, plan, "failed", "", {"error": str(error)}, None, ["photo_metadata_failed"])


def _extract_spreadsheet_metadata(sample: SampleFile, plan: dict[str, Any]) -> ExtractionResult:
    metadata: dict[str, Any] = {"suffix": sample.sample_path.suffix.lower(), "size_bytes": sample.sample_path.stat().st_size}
    warnings: list[str] = []
    if sample.sample_path.suffix.lower() in SPREADSHEET_EXTENSIONS:
        try:
            with zipfile.ZipFile(sample.sample_path) as workbook:
                names = workbook.namelist()
                metadata["zip_entry_count"] = len(names)
                metadata["sheet_entry_count"] = len([name for name in names if name.startswith("xl/worksheets/")])
                metadata["has_macros"] = "xl/vbaProject.bin" in names
        except zipfile.BadZipFile:
            warnings.append("spreadsheet_zip_metadata_failed")
    else:
        warnings.append("spreadsheet_parser_not_installed")
    return ExtractionResult(sample, plan, "metadata_extracted", "", metadata, None, warnings)


def _extract_ocr_page_level(
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
        metadata.update(_ocr_probe_metadata(sample))
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


def _ocr_probe_metadata(sample: SampleFile) -> dict[str, Any]:
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
            page_count = len(reader.pages)
            metadata["page_count"] = page_count
        except Exception as error:  # noqa: BLE001
            metadata["pdf_probe_error"] = str(error)
    return metadata


def _ocr_pil_image(sample: SampleFile, image: Image.Image, page_number: int, page_count: int, page_start: float) -> OcrPageResult:
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
        ocr_engine_version=_tesseract_version(),
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


def _ocr_document_from_pages(sample: SampleFile, pages: list[OcrPageResult], seconds: float) -> OcrDocumentResult:
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


def _failed_ocr_document(sample: SampleFile, warnings: list[str]) -> OcrDocumentResult:
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
    text = "\n".join(page.text for page in pages)
    if _looks_like_gibberish(text):
        return "gibberish_suspected"
    return None


def _ocr_evidence(extraction: ExtractionResult) -> dict[str, Any]:
    warnings = extraction.warnings
    fallback_provider = _warning_value(warnings, "ocr_fallback_used:")
    fallback_reason = _warning_value(warnings, "ocr_fallback_reason:")
    original_extraction = extraction.metadata.get("original_extraction")
    original_snippet = _warning_value(warnings, "ocr_original_snippet:")
    if not original_snippet and isinstance(original_extraction, dict):
        original_snippet = str(original_extraction.get("text_snippet") or "") or None
    fallback_snippet = _warning_value(warnings, "ocr_fallback_snippet:")
    if fallback_provider and not fallback_snippet:
        fallback_snippet = _shorten(extraction.text, 360) or None
    return {
        "fallback_used": bool(fallback_provider),
        "fallback_provider": fallback_provider,
        "fallback_reason": fallback_reason,
        "fallback_notes": _warning_values(warnings, "ocr_fallback_note:"),
        "original_text_snippet": original_snippet,
        "fallback_text_snippet": fallback_snippet,
        "final_text_snippet": _shorten(extraction.text, 360) or None,
    }


def _warning_value(warnings: list[str], prefix: str) -> str | None:
    values = _warning_values(warnings, prefix)
    return values[0] if values else None


def _warning_values(warnings: list[str], prefix: str) -> list[str]:
    return [warning[len(prefix) :] for warning in warnings if isinstance(warning, str) and warning.startswith(prefix)]


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


def _render_sample_images(sample: SampleFile) -> list[Image.Image]:
    if sample.sample_path.suffix.lower() in IMAGE_EXTENSIONS:
        return [Image.open(sample.sample_path)]
    if sample.sample_path.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium  # type: ignore

        pdf = pdfium.PdfDocument(str(sample.sample_path))
        images = []
        for page in pdf:
            bitmap = page.render(scale=2)
            images.append(bitmap.to_pil())
        return images
    raise ValueError("ocr_unsupported_file_type")


def _image_to_data_url(image: Image.Image) -> str:
    with io.BytesIO() as buffer:
        image.convert("RGB").save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _tesseract_version() -> str | None:
    try:
        _configure_tesseract_runtime()
        import pytesseract  # type: ignore

        return str(pytesseract.get_tesseract_version())
    except Exception:  # noqa: BLE001
        return None


def _configure_tesseract_runtime() -> str | None:
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


def build_ocr_summary(page_rows: list[dict[str, Any]], document_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_ocr_status: Counter[str] = Counter(str(row.get("ocr_status") or "unknown") for row in document_rows)
    by_quality: Counter[str] = Counter(str(row.get("quality") or "unknown") for row in document_rows)
    by_warning: Counter[str] = Counter()
    for row in [*page_rows, *document_rows]:
        for warning in row.get("warnings", []):
            by_warning[str(warning)] += 1
    page_seconds = [float(row.get("seconds") or 0) for row in page_rows]
    total_pages = len(page_rows)
    failed_pages = len([row for row in page_rows if row.get("ocr_status") == "failed"])
    return {
        "ocr_document_rows": len(document_rows),
        "ocr_page_rows": len(page_rows),
        "by_ocr_status": dict(sorted(by_ocr_status.items())),
        "by_quality": dict(sorted(by_quality.items())),
        "by_warning": dict(sorted(by_warning.items())),
        "total_pages": total_pages,
        "failed_pages": failed_pages,
        "failed_page_rate": round(failed_pages / total_pages, 4) if total_pages else 0,
        "total_ocr_seconds": round(sum(float(row.get("seconds") or 0) for row in document_rows), 4),
        "average_seconds_per_page": round(sum(page_seconds) / total_pages, 4) if total_pages else 0,
    }


def _chunk_row(extraction: ExtractionResult, chunk_index: int, chunk_kind: str, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": extraction.sample.source_path,
        "relative_path": extraction.sample.relative_path,
        "sample_path": str(extraction.sample.sample_path),
        "chunk_id": f"{extraction.sample.sample_group}:{extraction.sample.sample_number or 0}:{chunk_index}",
        "chunk_index": chunk_index,
        "chunk_kind": chunk_kind,
        "text": text,
        "metadata": metadata,
    }


def _with_added_warnings(extraction: ExtractionResult, warnings: list[str]) -> ExtractionResult:
    return ExtractionResult(
        sample=extraction.sample,
        plan=extraction.plan,
        extraction_status=extraction.extraction_status,
        text=extraction.text,
        metadata=extraction.metadata,
        page_count=extraction.page_count,
        warnings=[*extraction.warnings, *warnings],
    )


def _with_text_validation(extraction: ExtractionResult, validation: dict[str, Any]) -> ExtractionResult:
    return ExtractionResult(
        sample=extraction.sample,
        plan=extraction.plan,
        extraction_status=extraction.extraction_status,
        text=extraction.text,
        metadata={**extraction.metadata, "text_validation": validation},
        page_count=extraction.page_count,
        warnings=extraction.warnings,
    )


def _can_try_ocr(sample: SampleFile) -> bool:
    return sample.sample_path.suffix.lower() in IMAGE_EXTENSIONS or sample.sample_path.suffix.lower() == ".pdf"


def _update_summary_counters(counters: dict[str, Counter[str]], result: dict[str, Any]) -> None:
    counters["by_sample_group"][result["sample_group"]] += 1
    counters["by_final_class"][result["final_class"]] += 1
    counters["by_extraction_strategy"][result["extraction_strategy"]] += 1
    counters["by_extraction_status"][result["extraction_status"]] += 1
    counters["by_quality"][result["quality"]] += 1
    if result.get("ocr_status"):
        counters["by_ocr_status"][result["ocr_status"]] += 1
    ocr_quality = result["quality"] if result.get("ocr_status") else None
    if ocr_quality:
        counters["by_ocr_quality"][ocr_quality] += 1
    counters["by_chunk_count_bucket"][_chunk_count_bucket(result["chunk_count"])] += 1
    counters["by_embedding_status"][result["embedding_status"]] += 1
    counters["by_llm_status"][result.get("llm_status", "unknown")] += 1
    counters["by_top_tag_candidate"][result["top_tag_candidate"] or "none"] += 1
    for secondary_tag in result.get("secondary_tags", []):
        counters["by_secondary_tag"][secondary_tag] += 1
    counters["by_route_status"][result["route_status"]] += 1
    for warning in result["warnings"]:
        counters["by_warning"][warning] += 1


def _chunk_count_bucket(chunk_count: int) -> str:
    if chunk_count == 0:
        return "0"
    if chunk_count == 1:
        return "1"
    if chunk_count <= 5:
        return "2-5"
    return "6+"


def _load_rows_by_keys(path: str | Path) -> dict[str, dict[str, Any]]:
    rows_by_key: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(Path(path)):
        rows_by_key[row["source_path"]] = row
        rows_by_key[row["relative_path"]] = row
    return rows_by_key


def _lookup_by_sample(sample: SampleFile, rows_by_key: dict[str, dict[str, Any]], *, artifact_name: str) -> dict[str, Any]:
    row = rows_by_key.get(sample.source_path) or rows_by_key.get(sample.relative_path)
    if row is None:
        raise ValueError(f"Missing {artifact_name} row for {sample.relative_path}")
    return row


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as input_file:
        return [json.loads(line) for line in input_file if line.strip()]


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as output_file:
        for row in rows:
            _write_jsonl_row(output_file, row)


def _write_jsonl_row(output_file: TextIO, row: dict[str, Any]) -> None:
    output_file.write(json.dumps(row, sort_keys=True) + "\n")


def _progress(enabled: bool, message: str) -> None:
    if enabled:
        print(message, file=sys.stderr, flush=True)


def _shorten(text: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."


def _cortex_root_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[:-3].rstrip("/")
    return normalized


def _cortex_openai_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


def _cortex_ocr_pages(payload: dict[str, Any]) -> list[dict[str, Any]]:
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


def _normalize_ocr_confidence(value: Any) -> float | None:
    if not isinstance(value, int | float):
        return None
    confidence = float(value)
    if confidence <= 1.0:
        confidence *= 100
    return round(max(0.0, min(confidence, 100.0)), 2)


def _optional_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the QA sample tracer-bullet pipeline.")
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--corrected", default=str(DEFAULT_CORRECTED_PATH))
    parser.add_argument("--plan", default=str(DEFAULT_PLAN_PATH))
    parser.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY_PATH))
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--enable-llm-tags",
        action="store_true",
        help="Use configured LLM tag inspection. Defaults to SUNSHINE_LLM_TAG_PROVIDER, or auto when unset.",
    )
    parser.add_argument(
        "--llm-tag-provider",
        choices=["auto", "cortex", "openai", "disabled"],
        help="Override SUNSHINE_LLM_TAG_PROVIDER for this run.",
    )
    parser.add_argument(
        "--ocr-fallback-provider",
        choices=["openai", "cortex", "disabled"],
        help="OCR provider. cortex uses Cortex first and escalates poor, empty, failed, or suspicious OCR to OpenAI when configured.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress logging.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    load_pipeline_env()
    summary = run_sample_pipeline(
        args.input_root,
        output_dir=args.output_dir,
        corrected_path=args.corrected,
        plan_path=args.plan,
        taxonomy_path=args.taxonomy,
        limit=args.limit,
        llm_tag_inspector=llm_tag_inspector_from_env(
            enabled=args.enable_llm_tags,
            provider_override=args.llm_tag_provider or "auto",
        ),
        ocr_executor=ocr_executor_from_env(fallback_provider_override=args.ocr_fallback_provider),
        progress=not args.quiet,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
