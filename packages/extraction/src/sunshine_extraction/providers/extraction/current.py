"""Adapter around the current in-house extraction implementation."""

from __future__ import annotations

import time
from typing import Any

from sunshine_extraction.providers.extraction.base import ExtractionProviderAttempt
from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import ExtractionResult, OcrArtifacts, OcrExecutor, extract_content


class CurrentExtractionProvider:
    provider_name = "current"

    def dependency_status(self) -> dict[str, Any]:
        return {"provider": self.provider_name, "available": True, "local_only": True}

    def extract(
        self,
        sample: SampleFile,
        plan: dict[str, Any],
        *,
        ocr_executor: OcrExecutor | None = None,
        ocr_artifacts: OcrArtifacts | None = None,
    ) -> tuple[ExtractionResult, ExtractionProviderAttempt]:
        started = time.monotonic()
        extraction = extract_content(sample, plan, ocr_executor=ocr_executor, ocr_artifacts=ocr_artifacts)
        seconds = round(time.monotonic() - started, 6)
        return extraction, ExtractionProviderAttempt(
            provider=self.provider_name,
            status=extraction.extraction_status,
            strategy=plan.get("strategy"),
            seconds=seconds,
            warnings=extraction.warnings,
            metadata={
                "local_only": True,
                "page_count": extraction.page_count,
                "text_length": len(extraction.text or ""),
            },
        )

