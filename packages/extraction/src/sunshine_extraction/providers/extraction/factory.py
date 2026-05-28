"""Extraction provider selection for local-only graph runs."""

from __future__ import annotations

import os

from sunshine_extraction.providers.extraction.base import ExtractionProvider
from sunshine_extraction.providers.extraction.current import CurrentExtractionProvider
from sunshine_extraction.providers.extraction.docling_provider import DoclingExtractionProvider


def extraction_provider_from_env(provider_name_override: str | None = None) -> ExtractionProvider:
    provider_name = (provider_name_override or os.environ.get("SUNSHINE_EXTRACTION_PROVIDER") or "current").strip().lower()
    if provider_name in {"", "current", "native", "legacy"}:
        return CurrentExtractionProvider()
    if provider_name == "docling":
        return DoclingExtractionProvider()
    raise ValueError(f"Unsupported SUNSHINE_EXTRACTION_PROVIDER={provider_name!r}; expected current or docling")
