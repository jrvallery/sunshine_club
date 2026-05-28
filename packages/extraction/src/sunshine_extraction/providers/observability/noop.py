"""No-op observability provider."""

from __future__ import annotations

from typing import Any


class NoopObservabilityProvider:
    provider_name = "noop"

    def dependency_status(self) -> dict[str, Any]:
        return {"provider": self.provider_name, "available": True, "local_only": True}

    def record_event(self, name: str, payload: dict[str, Any]) -> None:
        del name, payload
