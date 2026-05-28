"""Docling extraction provider scaffold.

Docling is optional at import time so the current test/dev environment can run
before the heavy local parser stack is installed.
"""

from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path
from typing import Any

from sunshine_extraction.providers.extraction.base import ExtractionProviderAttempt
from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import ExtractionResult, OcrArtifacts, OcrExecutor


class DoclingExtractionProvider:
    provider_name = "docling"

    def __init__(self, converter: Any | None = None) -> None:
        self._converter = converter

    def dependency_status(self) -> dict[str, Any]:
        cache_status = _rapidocr_model_cache_status()
        cache_required = _local_model_cache_required()
        if self._converter is not None:
            return {
                "provider": self.provider_name,
                "available": True,
                "local_only": True,
                "model_cache": cache_status,
                "model_cache_required": cache_required,
            }
        try:
            import docling.document_converter  # noqa: F401
        except Exception as error:  # noqa: BLE001 - optional dependency probe.
            return {
                "provider": self.provider_name,
                "available": False,
                "local_only": True,
                "missing": ["docling"],
                "error": error.__class__.__name__,
            }
        if cache_required and not cache_status.get("ready"):
            return {
                "provider": self.provider_name,
                "available": False,
                "local_only": True,
                "missing": ["rapidocr_model_cache"],
                "model_cache": cache_status,
                "model_cache_required": True,
                "error": "model_cache_missing",
            }
        return {
            "provider": self.provider_name,
            "available": True,
            "local_only": True,
            "model_cache": cache_status,
            "model_cache_required": cache_required,
        }

    def extract(
        self,
        sample: SampleFile,
        plan: dict[str, Any],
        *,
        ocr_executor: OcrExecutor | None = None,
        ocr_artifacts: OcrArtifacts | None = None,
    ) -> tuple[ExtractionResult, ExtractionProviderAttempt]:
        del ocr_executor, ocr_artifacts
        started = time.monotonic()
        cache_failure = _local_model_cache_failure()
        if cache_failure:
            extraction = ExtractionResult(
                sample=sample,
                plan={**plan, "provider": self.provider_name},
                extraction_status="failed",
                text="",
                metadata={
                    "provider": self.provider_name,
                    "local_only": True,
                    "error": cache_failure["error"],
                    "model_cache": cache_failure["model_cache"],
                    "model_cache_required": True,
                },
                page_count=None,
                warnings=["docling_model_cache_missing"],
            )
            seconds = round(time.monotonic() - started, 6)
            return extraction, ExtractionProviderAttempt(
                provider=self.provider_name,
                status="failed",
                strategy=plan.get("strategy"),
                seconds=seconds,
                warnings=extraction.warnings,
                metadata={
                    "local_only": True,
                    "text_length": 0,
                    "page_count": None,
                    "model_cache": cache_failure["model_cache"],
                    "model_cache_required": True,
                    "error": cache_failure["error"],
                },
            )
        try:
            converter = self._converter or self._build_converter()
            result = converter.convert(str(sample.sample_path))
            document = result.document
            text = _export_markdown(document)
            structure = _docling_structure(document)
            metadata = {
                "provider": self.provider_name,
                "local_only": True,
                "structure_provider": self.provider_name,
                "raw_provider_type": result.__class__.__name__,
                "docling_structure": structure,
            }
            extraction = ExtractionResult(
                sample=sample,
                plan={**plan, "provider": self.provider_name},
                extraction_status="extracted" if text.strip() else "failed",
                text=text,
                metadata=metadata,
                page_count=structure.get("page_count"),
                warnings=[] if text.strip() else ["docling_empty_text"],
            )
        except Exception as error:  # noqa: BLE001 - provider failures route through graph.
            extraction = ExtractionResult(
                sample=sample,
                plan={**plan, "provider": self.provider_name},
                extraction_status="failed",
                text="",
                metadata={"provider": self.provider_name, "local_only": True, "error": error.__class__.__name__},
                page_count=None,
                warnings=[f"docling_provider_failed:{error.__class__.__name__}"],
            )
        seconds = round(time.monotonic() - started, 6)
        return extraction, ExtractionProviderAttempt(
            provider=self.provider_name,
            status=extraction.extraction_status,
            strategy=plan.get("strategy"),
            seconds=seconds,
            warnings=extraction.warnings,
            metadata={
                "local_only": True,
                "text_length": len(extraction.text or ""),
                "page_count": extraction.page_count,
                "structure": extraction.metadata.get("docling_structure", {}),
            },
        )

    def _build_converter(self) -> Any:
        try:
            from docling.document_converter import DocumentConverter
        except Exception as error:  # noqa: BLE001 - normalize optional dependency failure.
            raise RuntimeError("docling is not installed") from error
        return DocumentConverter()


def _export_markdown(document: Any) -> str:
    exporter = getattr(document, "export_to_markdown", None)
    if callable(exporter):
        value = exporter()
        return value if isinstance(value, str) else str(value or "")
    exporter = getattr(document, "export_to_text", None)
    if callable(exporter):
        value = exporter()
        return value if isinstance(value, str) else str(value or "")
    return str(document or "")


def _docling_structure(document: Any) -> dict[str, Any]:
    page_rows = _docling_pages(getattr(document, "pages", None), text_by_page=_docling_text_by_page(getattr(document, "texts", None)))
    pages = len(page_rows) if page_rows else _safe_len(getattr(document, "pages", None))
    tables = _safe_len(getattr(document, "tables", None))
    pictures = _safe_len(getattr(document, "pictures", None))
    groups = _safe_len(getattr(document, "groups", None))
    texts = _safe_len(getattr(document, "texts", None))
    page_count = pages if pages is not None else _safe_int(getattr(document, "num_pages", None))
    return {
        "page_count": page_count,
        "table_count": tables,
        "picture_count": pictures,
        "group_count": groups,
        "text_item_count": texts,
        "pages": page_rows,
    }


def _docling_pages(pages: Any, *, text_by_page: dict[int, str] | None = None) -> list[dict[str, Any]]:
    if not pages:
        return []
    page_text = text_by_page or {}
    rows: list[dict[str, Any]] = []
    try:
        iterator = list(pages.values()) if isinstance(pages, dict) else list(pages)
    except TypeError:
        return []
    for fallback_index, page in enumerate(iterator, start=1):
        page_number = _safe_int(getattr(page, "page_no", None)) or _safe_int(getattr(page, "page_number", None)) or fallback_index
        text = _safe_page_text(page) or page_text.get(page_number, "")
        row = {
            "page_number": page_number,
            "text": text,
            "text_length": len(text),
            "word_count": len(text.split()),
            "quality": "provider_page",
            "provider": "docling",
        }
        rows.append(row)
    return rows


def _docling_text_by_page(text_items: Any) -> dict[int, str]:
    if not text_items:
        return {}
    try:
        iterator = list(text_items.values()) if isinstance(text_items, dict) else list(text_items)
    except TypeError:
        return {}
    by_page: dict[int, list[str]] = {}
    for item in iterator:
        text = _safe_text_item_text(item)
        if not text:
            continue
        for page_number in _safe_text_item_page_numbers(item):
            by_page.setdefault(page_number, []).append(text)
    return {page_number: "\n\n".join(parts) for page_number, parts in by_page.items()}


def _safe_text_item_text(item: Any) -> str:
    for attr_name in ("text", "orig", "content", "caption"):
        value = getattr(item, attr_name, None)
        if value:
            return str(value)
    exporter = getattr(item, "export_to_text", None)
    if callable(exporter):
        try:
            value = exporter()
        except Exception:  # noqa: BLE001 - best-effort provider metadata.
            return ""
        return str(value or "")
    return ""


def _safe_text_item_page_numbers(item: Any) -> list[int]:
    provenance = getattr(item, "prov", None) or getattr(item, "provenance", None)
    if not provenance:
        page_number = _safe_int(getattr(item, "page_no", None)) or _safe_int(getattr(item, "page_number", None))
        return [page_number] if page_number is not None else []
    try:
        entries = list(provenance)
    except TypeError:
        entries = [provenance]
    page_numbers: list[int] = []
    for entry in entries:
        page_number = _safe_int(getattr(entry, "page_no", None)) or _safe_int(getattr(entry, "page_number", None))
        if page_number is not None:
            page_numbers.append(page_number)
    return page_numbers


def _safe_page_text(page: Any) -> str:
    for method_name in ("export_to_text", "export_to_markdown"):
        method = getattr(page, method_name, None)
        if callable(method):
            try:
                value = method()
            except Exception:  # noqa: BLE001 - page text is best-effort metadata.
                continue
            if value:
                return str(value)
    for attr_name in ("text", "content", "caption"):
        value = getattr(page, attr_name, None)
        if value:
            return str(value)
    return ""


def _safe_len(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return len(value)
    except TypeError:
        return None


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _rapidocr_model_cache_status() -> dict[str, Any]:
    required_files = [
        "ch_PP-OCRv4_det_mobile.pth",
        "ch_ptocr_mobile_v2.0_cls_mobile.pth",
        "ch_PP-OCRv4_rec_mobile.pth",
    ]
    spec = importlib.util.find_spec("rapidocr")
    if spec is None or spec.origin is None:
        return {
            "provider": "rapidocr",
            "ready": False,
            "path": None,
            "required_files": required_files,
            "present_files": [],
            "missing_files": required_files,
        }
    package_root = Path(spec.origin).parent
    model_dir = package_root / "models"
    present_files = sorted(path.name for path in model_dir.glob("*") if path.is_file()) if model_dir.exists() else []
    missing_files = [name for name in required_files if name not in present_files]
    return {
        "provider": "rapidocr",
        "ready": not missing_files,
        "path": str(model_dir),
        "required_files": required_files,
        "present_files": present_files,
        "missing_files": missing_files,
    }


def _local_model_cache_required() -> bool:
    value = (
        os.environ.get("SUNSHINE_REQUIRE_LOCAL_MODEL_CACHE")
        or ("true" if (os.environ.get("SUNSHINE_RUNTIME_MODE") or os.environ.get("SUNSHINE_ENV") or "").strip().lower() == "production" else "")
    )
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _local_model_cache_failure() -> dict[str, Any] | None:
    if not _local_model_cache_required():
        return None
    cache_status = _rapidocr_model_cache_status()
    if cache_status.get("ready"):
        return None
    return {"error": "model_cache_missing", "model_cache": cache_status}
