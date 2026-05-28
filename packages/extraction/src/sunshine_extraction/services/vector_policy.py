"""Vector-store policy for local development and production V2 runs."""

from __future__ import annotations

import os
from typing import Any


LOCAL_VECTOR_STORE_NAMES = {"noop", "qdrant", "sqlite_golden"}


def vector_store_policy_from_env() -> dict[str, Any]:
    """Return the active local vector-store policy.

    Qdrant is the V2 production default. Local/dev runs may stay side-effect
    free with ``noop`` unless Qdrant is explicitly required.
    """

    mode = _runtime_mode()
    qdrant_required = _truthy(os.environ.get("SUNSHINE_REQUIRE_QDRANT")) or mode == "production"
    configured = (os.environ.get("SUNSHINE_VECTOR_STORE") or ("qdrant" if qdrant_required else "noop")).strip().lower()
    if configured in {"", "none", "disabled"}:
        configured = "noop"
    if configured not in LOCAL_VECTOR_STORE_NAMES:
        raise ValueError(
            f"Unsupported SUNSHINE_VECTOR_STORE={configured!r}; expected noop, qdrant, or sqlite_golden."
        )
    if qdrant_required and configured != "qdrant":
        raise ValueError("Qdrant is required for production V2 runs; set SUNSHINE_VECTOR_STORE=qdrant.")
    return {
        "runtime_mode": mode,
        "provider": configured,
        "qdrant_required": qdrant_required,
        "qdrant_required_reason": "production_mode" if mode == "production" else ("explicit_env" if qdrant_required else "not_required"),
        "qdrant_url": os.environ.get("SUNSHINE_QDRANT_URL") or "http://127.0.0.1:6333",
        "qdrant_collection": os.environ.get("SUNSHINE_QDRANT_COLLECTION") or "sunshine_chunks",
        "embedding_dimensions": _optional_positive_int(os.environ.get("SUNSHINE_EMBEDDING_DIMENSIONS")),
        "local_only": True,
    }


def _runtime_mode() -> str:
    value = (os.environ.get("SUNSHINE_RUNTIME_MODE") or os.environ.get("SUNSHINE_ENV") or "development").strip().lower()
    if value in {"prod", "production", "v2-production"}:
        return "production"
    return "development"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on", "required"}


def _optional_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
