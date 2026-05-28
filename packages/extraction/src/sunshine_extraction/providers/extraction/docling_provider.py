"""Docling extraction provider scaffold.

Docling is optional at import time so the current test/dev environment can run
before the heavy local parser stack is installed.
"""

from __future__ import annotations

import time
from typing import Any

from sunshine_extraction.providers.extraction.base import ExtractionProviderAttempt
from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import ExtractionResult, OcrArtifacts, OcrExecutor


class DoclingExtractionProvider:
    provider_name = "docling"

    def __init__(self, converter: Any | None = None) -> None:
        self._converter = converter

    def dependency_status(self) -> dict[str, Any]:
        if self._converter is not None:
            return {"provider": self.provider_name, "available": True, "local_only": True}
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
        return {"provider": self.provider_name, "available": True, "local_only": True}

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
    pages = _safe_len(getattr(document, "pages", None))
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
    }


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
