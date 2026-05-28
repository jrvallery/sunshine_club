"""Observability provider selection."""

from __future__ import annotations

import os

from sunshine_extraction.providers.observability.base import ObservabilityProvider
from sunshine_extraction.providers.observability.langfuse import LangfuseObservabilityProvider
from sunshine_extraction.providers.observability.noop import NoopObservabilityProvider


def observability_provider_from_env(provider_name_override: str | None = None) -> ObservabilityProvider:
    provider_name = (provider_name_override or os.environ.get("SUNSHINE_OBSERVABILITY_PROVIDER") or "noop").strip().lower()
    if provider_name in {"", "none", "disabled", "noop"}:
        return NoopObservabilityProvider()
    if provider_name == "langfuse":
        return LangfuseObservabilityProvider()
    return NoopObservabilityProvider()


__all__ = ["observability_provider_from_env"]
