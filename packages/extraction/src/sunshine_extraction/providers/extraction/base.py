"""Base contracts for local extraction/parser providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import ExtractionResult, OcrArtifacts, OcrExecutor


@dataclass(frozen=True)
class ExtractionProviderAttempt:
    provider: str
    status: str
    strategy: str | None
    seconds: float | None
    warnings: list[str]
    metadata: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


class ExtractionProvider(Protocol):
    provider_name: str

    def dependency_status(self) -> dict[str, Any]:
        """Return local dependency health without calling hosted services."""

    def extract(
        self,
        sample: SampleFile,
        plan: dict[str, Any],
        *,
        ocr_executor: OcrExecutor | None = None,
        ocr_artifacts: OcrArtifacts | None = None,
    ) -> tuple[ExtractionResult, ExtractionProviderAttempt]:
        """Extract a sample using the local provider."""

