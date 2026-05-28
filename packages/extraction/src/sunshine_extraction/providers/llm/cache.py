"""LLM prompt cache-key helpers."""

from __future__ import annotations

import hashlib


def llm_cache_key(*, prompt: str, provider: str, model: str, schema_version: str = "v1") -> str:
    payload = "\n".join([provider, model, schema_version, prompt])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["llm_cache_key"]
