"""Environment loading helpers for CLI entry points."""

from __future__ import annotations

import os
from pathlib import Path


def load_pipeline_env(env_path: str | Path | None = ".env") -> None:
    """Load optional `.env` configuration and normalize Cortex aliases."""

    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
    except Exception:  # noqa: BLE001 - .env support is best-effort for CLI convenience.
        pass

    cortex_api = os.environ.get("CORTEX_API_KEY")
    if cortex_api and not os.environ.get("CORTEX_OPENAI_API_KEY"):
        os.environ["CORTEX_OPENAI_API_KEY"] = cortex_api
    cortex_base = os.environ.get("CORTEX_BASE_URL")
    if cortex_base and not os.environ.get("CORTEX_OPENAI_BASE_URL"):
        os.environ["CORTEX_OPENAI_BASE_URL"] = _cortex_openai_base_url(cortex_base)

    openai_api = os.environ.get("OPENAI_API")
    if openai_api and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = openai_api


def _cortex_openai_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized}/v1"
