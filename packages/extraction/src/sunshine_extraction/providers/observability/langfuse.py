"""Self-hosted Langfuse observability provider boundary."""

from __future__ import annotations

import os
from typing import Any


class LangfuseObservabilityProvider:
    provider_name = "langfuse"

    def __init__(self, *, host: str | None = None) -> None:
        self.host = (host or os.environ.get("LANGFUSE_HOST") or "").rstrip("/")

    def dependency_status(self) -> dict[str, Any]:
        try:
            import langfuse  # noqa: F401
        except Exception as error:  # noqa: BLE001
            return {
                "provider": self.provider_name,
                "available": False,
                "local_only": _is_local_host(self.host),
                "host": self.host,
                "missing": ["langfuse"],
                "error": error.__class__.__name__,
            }
        return {"provider": self.provider_name, "available": bool(self.host), "local_only": _is_local_host(self.host), "host": self.host}

    def record_event(self, name: str, payload: dict[str, Any]) -> None:
        del name, payload


def _is_local_host(host: str) -> bool:
    return not host or "localhost" in host or "127.0.0.1" in host or host.startswith("http://192.168.") or host.startswith("http://10.")
