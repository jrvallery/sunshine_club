"""Provider registry defaults for local-only V2 graph runs."""

from __future__ import annotations

from sunshine_extraction.config.models import ProviderConfig

DEFAULT_PROVIDER_REGISTRY = {
    "extraction.current": ProviderConfig(name="current"),
    "extraction.docling": ProviderConfig(name="docling"),
    "ocr.tesseract": ProviderConfig(name="tesseract"),
    "ocr.cortex": ProviderConfig(name="cortex"),
    "vectorstore.noop": ProviderConfig(name="noop"),
    "vectorstore.qdrant": ProviderConfig(name="qdrant"),
    "llm.disabled": ProviderConfig(name="disabled"),
    "llm.cortex": ProviderConfig(name="cortex"),
}
