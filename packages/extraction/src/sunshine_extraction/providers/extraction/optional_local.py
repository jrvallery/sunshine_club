"""Optional local parser provider boundaries."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.providers.extraction.base import ExtractionProviderAttempt
from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import ExtractionResult, OcrArtifacts, OcrExecutor


class OptionalLocalExtractionProvider:
    provider_name = "optional_local"
    package_name: str | None = None
    not_enabled_warning: str = "optional_local_provider_not_enabled"

    def dependency_status(self) -> dict[str, Any]:
        if not self.package_name:
            return {"provider": self.provider_name, "available": False, "local_only": True, "missing": [self.provider_name]}
        try:
            __import__(self.package_name)
        except Exception as error:  # noqa: BLE001
            return {
                "provider": self.provider_name,
                "available": False,
                "local_only": True,
                "missing": [self.package_name],
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
        warning = self.not_enabled_warning
        extraction = ExtractionResult(
            sample=sample,
            plan={**plan, "provider": self.provider_name},
            extraction_status="failed",
            text="",
            metadata={"provider": self.provider_name, "local_only": True, "dependency_status": self.dependency_status()},
            page_count=None,
            warnings=[warning],
        )
        return extraction, ExtractionProviderAttempt(
            provider=self.provider_name,
            status="skipped",
            strategy=plan.get("strategy"),
            seconds=0,
            warnings=[warning],
            metadata={"local_only": True, "dependency_status": extraction.metadata["dependency_status"]},
        )
