"""Provider registry defaults for local-only V2 graph runs."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sunshine_extraction.config.models import ProviderConfig

DEFAULT_PROVIDER_REGISTRY = {
    "extraction.current": ProviderConfig(name="current", capability="extraction"),
    "extraction.docling": ProviderConfig(name="docling", capability="extraction", package="docling"),
    "extraction.mineru": ProviderConfig(name="mineru", capability="extraction", package="mineru"),
    "extraction.ragflow_deepdoc": ProviderConfig(name="ragflow_deepdoc", capability="extraction", package="deepdoc"),
    "extraction.unstructured": ProviderConfig(name="unstructured", capability="extraction", package="unstructured"),
    "ocr.tesseract": ProviderConfig(name="tesseract", capability="ocr", package="pytesseract"),
    "ocr.cortex": ProviderConfig(name="cortex", capability="ocr"),
    "ocr.openai": ProviderConfig(name="blocked_hosted_openai", capability="ocr", enabled=False, hosted=True, local_only=False),
    "vectorstore.noop": ProviderConfig(name="noop", capability="vectorstore"),
    "vectorstore.qdrant": ProviderConfig(name="qdrant", capability="vectorstore", package="qdrant-client"),
    "vectorstore.sqlite_golden": ProviderConfig(name="sqlite_golden", capability="vectorstore"),
    "retrieval.sqlite_semantic_index": ProviderConfig(name="sqlite_semantic_index", capability="retrieval"),
    "retrieval.qdrant": ProviderConfig(name="qdrant", capability="retrieval", package="qdrant-client"),
    "reranking.cortex": ProviderConfig(name="cortex", capability="reranking"),
    "llm.disabled": ProviderConfig(name="disabled", capability="llm", enabled=False),
    "llm.cortex": ProviderConfig(name="cortex", capability="llm"),
    "embedding.placeholder": ProviderConfig(name="placeholder", capability="embedding"),
    "embedding.cortex": ProviderConfig(name="cortex", capability="embedding"),
    "embedding.openai": ProviderConfig(name="blocked_hosted_openai", capability="embedding", enabled=False, hosted=True, local_only=False),
    "observability.noop": ProviderConfig(name="noop", capability="observability"),
    "observability.langfuse": ProviderConfig(name="langfuse", capability="observability", package="langfuse"),
}

REQUIRED_CAPABILITIES = {
    "embedding",
    "extraction",
    "llm",
    "observability",
    "ocr",
    "retrieval",
    "reranking",
    "vectorstore",
}


def provider_registry_rows(registry: dict[str, ProviderConfig] | None = None) -> list[dict[str, Any]]:
    active_registry = registry or DEFAULT_PROVIDER_REGISTRY
    return [{"key": key, **config.as_row()} for key, config in sorted(active_registry.items())]


def validate_provider_registry(registry: dict[str, ProviderConfig] | None = None) -> dict[str, Any]:
    active_registry = registry or DEFAULT_PROVIDER_REGISTRY
    errors: list[str] = []
    by_capability: dict[str, list[str]] = defaultdict(list)
    for key, config in sorted(active_registry.items()):
        if config.enabled and config.hosted:
            errors.append(f"{key}: hosted provider is enabled")
        if config.enabled and not config.local_only:
            errors.append(f"{key}: enabled provider is not local-only")
        if config.enabled:
            by_capability[config.capability].append(key)
    missing_capabilities = sorted(capability for capability in REQUIRED_CAPABILITIES if not by_capability.get(capability))
    for capability in missing_capabilities:
        errors.append(f"{capability}: no enabled provider")
    return {
        "ok": not errors,
        "errors": errors,
        "missing_capabilities": missing_capabilities,
        "enabled_by_capability": {capability: keys for capability, keys in sorted(by_capability.items())},
        "provider_count": len(active_registry),
    }


__all__ = ["DEFAULT_PROVIDER_REGISTRY", "REQUIRED_CAPABILITIES", "provider_registry_rows", "validate_provider_registry"]
