"""OpenAI-compatible vision OCR provider.

This provider is intentionally constructed only when the run explicitly selects
the hosted OpenAI OCR fallback path. Production local-only policy remains
enforced separately by provider-policy validation.
"""

from __future__ import annotations

import base64
import io
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image

from sunshine_extraction.domain.extraction import OcrDocumentResult, OcrExecutor, OcrPageResult
from sunshine_extraction.providers.extraction.ocr_common import failed_ocr_document, ocr_document_from_pages, shorten
from sunshine_extraction.services.content import IMAGE_EXTENSIONS, SampleFile


OCR_FALLBACK_DEFAULT_MAX_PAGES = 25

class HostedOpenAIOcrExecutor:
    def __init__(self, *_args, **_kwargs) -> None:
        raise ValueError("Hosted OpenAI OCR is not allowed; use local Cortex OCR or Tesseract")


class OpenAIVisionOcrExecutor(OcrExecutor):
    """OCR executor backed by OpenAI chat-completions vision models."""

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
            raise ValueError("OPENAI_API_KEY or OPENAI_API is required for OpenAI OCR fallback")
        if not model:
            raise ValueError("model is required for OpenAI OCR fallback")
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
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
        del plan
        start = time.monotonic()
        try:
            images = _render_sample_images(sample)
        except Exception as error:  # noqa: BLE001
            return failed_ocr_document(sample, [f"ocr_fallback_render_failed:{type(error).__name__}"]), []

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
        return ocr_document_from_pages(sample, pages, time.monotonic() - start), pages

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
        return text, max(0.0, min(float(confidence), 1.0)), [f"ocr_fallback_note:{shorten(note, 120)}" for note in notes[:3]]


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


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise json.JSONDecodeError("No JSON object found in OCR response", stripped, 0)
    return stripped[start : end + 1]


__all__ = ["HostedOpenAIOcrExecutor", "OpenAIVisionOcrExecutor"]
