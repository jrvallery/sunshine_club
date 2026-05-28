"""Observability provider contracts."""

from __future__ import annotations

from typing import Any, Protocol


class ObservabilityProvider(Protocol):
    provider_name: str

    def dependency_status(self) -> dict[str, Any]:
        """Return observability provider health."""

    def record_event(self, name: str, payload: dict[str, Any]) -> None:
        """Record an observability event."""
