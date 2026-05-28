"""Rerank cache-key helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def rerank_cache_key(*, query_text: str, documents: list[dict[str, Any]], provider: str, model: str, limit: int) -> str:
    payload = {
        "documents": documents,
        "limit": limit,
        "model": model,
        "provider": provider,
        "query_text": query_text,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


__all__ = ["rerank_cache_key"]
