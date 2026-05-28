"""Provider policy helpers for local-only production execution."""

from __future__ import annotations

import os


HOSTED_PROVIDER_NAMES = {"openai", "gemini", "anthropic", "cohere", "mistral"}
LOCAL_EXTRACTION_PROVIDER_NAMES = {"current", "docling", "mineru", "ragflow_deepdoc", "unstructured"}


def is_hosted_provider_name(provider_name: str | None) -> bool:
    normalized = (provider_name or "").strip().lower()
    return normalized in HOSTED_PROVIDER_NAMES


def assert_local_provider(provider_name: str | None, *, purpose: str) -> None:
    if is_hosted_provider_name(provider_name):
        raise ValueError(f"Hosted provider '{provider_name}' is not allowed for {purpose}; Sunshine V2 is local-only.")


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
