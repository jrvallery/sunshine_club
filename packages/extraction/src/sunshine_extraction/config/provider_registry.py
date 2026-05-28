"""Provider registry defaults for local-only V2 graph runs."""

from __future__ import annotations

from sunshine_extraction.config.models import ProviderConfig

DEFAULT_PROVIDER_REGISTRY = {
    "extraction.current": ProviderConfig(name="current"),
    "extraction.docling": ProviderConfig(name="docling"),
    "extraction.mineru": ProviderConfig(name="mineru"),
    "extraction.ragflow_deepdoc": ProviderConfig(name="ragflow_deepdoc"),
    "extraction.unstructured": ProviderConfig(name="unstructured"),
    "ocr.tesseract": ProviderConfig(name="tesseract"),
    "ocr.cortex": ProviderConfig(name="cortex"),
    "ocr.openai": ProviderConfig(name="blocked_hosted_openai", enabled=False),
    "vectorstore.noop": ProviderConfig(name="noop"),
    "vectorstore.qdrant": ProviderConfig(name="qdrant"),
    "vectorstore.sqlite_golden": ProviderConfig(name="sqlite_golden"),
    "llm.disabled": ProviderConfig(name="disabled"),
    "llm.cortex": ProviderConfig(name="cortex"),
    "observability.noop": ProviderConfig(name="noop"),
    "observability.langfuse": ProviderConfig(name="langfuse"),
}
