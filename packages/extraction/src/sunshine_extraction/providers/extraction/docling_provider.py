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
        converter = self._converter or self._build_converter()
        try:
            result = converter.convert(str(sample.sample_path))
            document = result.document
            text = document.export_to_markdown()
            metadata = {
                "provider": self.provider_name,
                "local_only": True,
                "structure_provider": self.provider_name,
                "raw_provider_type": result.__class__.__name__,
            }
            extraction = ExtractionResult(
                sample=sample,
                plan={**plan, "provider": self.provider_name},
                extraction_status="extracted" if text.strip() else "failed",
                text=text,
                metadata=metadata,
                page_count=None,
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
            metadata={"local_only": True, "text_length": len(extraction.text or "")},
        )

    def _build_converter(self) -> Any:
        try:
            from docling.document_converter import DocumentConverter
        except Exception as error:  # noqa: BLE001 - normalize optional dependency failure.
            raise RuntimeError("docling is not installed") from error
        return DocumentConverter()

