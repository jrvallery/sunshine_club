"""Embedding cache provider placeholder.

The V2 architecture reserves this module for content/model-hash caching before
provider calls. The current graph records cache misses implicitly by making each
embedding request; no persistent cache is enabled yet.
"""

from __future__ import annotations

import hashlib


def embedding_cache_key(*, text: str, provider: str, model: str, dimensions: int) -> str:
    payload = "\n".join([provider, model, str(dimensions), text])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["embedding_cache_key"]
