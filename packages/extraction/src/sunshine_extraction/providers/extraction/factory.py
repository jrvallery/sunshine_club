"""Extraction provider selection for local-only graph runs."""

from __future__ import annotations

import os

from sunshine_extraction.providers.extraction.base import ExtractionProvider
from sunshine_extraction.providers.extraction.current import CurrentExtractionProvider
from sunshine_extraction.providers.extraction.docling_provider import DoclingExtractionProvider
from sunshine_extraction.providers.extraction.mineru_provider import MinerUExtractionProvider
from sunshine_extraction.providers.extraction.ragflow_deepdoc_provider import RAGFlowDeepDocExtractionProvider
from sunshine_extraction.providers.extraction.unstructured_provider import UnstructuredExtractionProvider


def extraction_provider_from_env(provider_name_override: str | None = None) -> ExtractionProvider:
    provider_name = (provider_name_override or os.environ.get("SUNSHINE_EXTRACTION_PROVIDER") or "current").strip().lower()
    if provider_name in {"", "current", "native", "legacy"}:
        return CurrentExtractionProvider()
    if provider_name == "docling":
        return DoclingExtractionProvider()
    if provider_name == "mineru":
        return MinerUExtractionProvider()
    if provider_name in {"ragflow_deepdoc", "deepdoc"}:
        return RAGFlowDeepDocExtractionProvider()
    if provider_name == "unstructured":
        return UnstructuredExtractionProvider()
    raise ValueError(
        f"Unsupported SUNSHINE_EXTRACTION_PROVIDER={provider_name!r}; "
        "expected current, docling, mineru, ragflow_deepdoc, or unstructured"
    )
