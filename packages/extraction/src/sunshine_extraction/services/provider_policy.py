"""Provider policy helpers for local-only production execution."""

from __future__ import annotations


HOSTED_PROVIDER_NAMES = {"openai", "gemini", "anthropic", "cohere", "mistral"}


def is_hosted_provider_name(provider_name: str | None) -> bool:
    normalized = (provider_name or "").strip().lower()
    return normalized in HOSTED_PROVIDER_NAMES


def assert_local_provider(provider_name: str | None, *, purpose: str) -> None:
    if is_hosted_provider_name(provider_name):
        raise ValueError(f"Hosted provider '{provider_name}' is not allowed for {purpose}; Sunshine V2 is local-only.")

