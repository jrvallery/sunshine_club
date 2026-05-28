"""Provider policy helpers for local-only production execution."""

from __future__ import annotations

import os
from typing import Any


HOSTED_PROVIDER_NAMES = {"openai", "gemini", "anthropic", "cohere", "mistral"}
LOCAL_EXTRACTION_PROVIDER_NAMES = {"current", "docling", "mineru", "ragflow_deepdoc", "unstructured"}
PROVIDER_ENV_KEYS = {
    "SUNSHINE_EMBEDDING_PROVIDER": "embedding provider",
    "SUNSHINE_LLM_TAG_PROVIDER": "LLM tag provider",
    "SUNSHINE_OCR_FALLBACK_PROVIDER": "OCR fallback provider",
    "SUNSHINE_OCR_PARSER_PROVIDER": "OCR parser provider",
    "SUNSHINE_TEXT_PARSER_PROVIDER": "text parser provider",
    "SUNSHINE_DEFAULT_PARSER_PROVIDER": "default parser provider",
    "SUNSHINE_RETRIEVAL_PROVIDER": "retrieval provider",
    "SUNSHINE_RERANK_PROVIDER": "rerank provider",
    "SUNSHINE_VECTOR_STORE": "vector store provider",
}


def is_hosted_provider_name(provider_name: str | None) -> bool:
    normalized = (provider_name or "").strip().lower()
    return normalized in HOSTED_PROVIDER_NAMES


def assert_local_provider(provider_name: str | None, *, purpose: str) -> None:
    if is_hosted_provider_name(provider_name):
        raise ValueError(f"Hosted provider '{provider_name}' is not allowed for {purpose}; Sunshine V2 is local-only.")


def assert_production_local_only_environment(env: dict[str, Any] | None = None) -> None:
    """Fail closed when production env provider settings name hosted APIs."""

    active_env = env or os.environ
    mode = _runtime_mode(active_env)
    if mode != "production":
        return
    violations = []
    for key, purpose in sorted(PROVIDER_ENV_KEYS.items()):
        value = str(active_env.get(key) or "").strip().lower()
        if is_hosted_provider_name(value):
            violations.append(f"{key}={value} ({purpose})")
    if violations:
        joined = ", ".join(violations)
        raise ValueError(f"Production Sunshine V2 runs are local-only; hosted provider settings are blocked: {joined}")


def parser_provider_for_strategy(strategy: str, *, default: str = "current") -> str:
    """Return the configured local parser preference for an extraction strategy.

    This is the reversible promotion switch for benchmarked parser providers.
    It intentionally accepts only local provider names.
    """

    env_key = "SUNSHINE_OCR_PARSER_PROVIDER" if strategy == "ocr_page_level" else "SUNSHINE_TEXT_PARSER_PROVIDER"
    provider_name = os.environ.get(env_key) or os.environ.get("SUNSHINE_DEFAULT_PARSER_PROVIDER") or default
    return normalize_local_extraction_provider(provider_name, purpose=f"{strategy} parser policy")


def normalize_local_extraction_provider(provider_name: str | None, *, purpose: str) -> str:
    normalized = (provider_name or "").strip().lower()
    if normalized == "deepdoc":
        normalized = "ragflow_deepdoc"
    if normalized in {"", "native", "legacy"}:
        normalized = "current"
    assert_local_provider(normalized, purpose=purpose)
    if normalized not in LOCAL_EXTRACTION_PROVIDER_NAMES:
        raise ValueError(
            f"Unsupported local extraction provider '{provider_name}' for {purpose}; "
            "expected current, docling, mineru, ragflow_deepdoc, or unstructured."
        )
    return normalized


def _runtime_mode(env: dict[str, Any]) -> str:
    value = str(env.get("SUNSHINE_RUNTIME_MODE") or env.get("SUNSHINE_ENV") or "development").strip().lower()
    if value in {"prod", "production", "v2-production"}:
        return "production"
    return "development"
