"""Local-only infrastructure readiness checks for V2 pipeline dependencies."""

from __future__ import annotations

import os
from typing import Any

from sunshine_extraction.providers.extraction import DoclingExtractionProvider
from sunshine_extraction.providers.vectorstores import QdrantVectorStoreProvider


def local_infrastructure_status() -> dict[str, Any]:
    postgres_url = os.environ.get("DATABASE_URL") or os.environ.get("SUNSHINE_DATABASE_URL")
    qdrant = QdrantVectorStoreProvider()
    docling = DoclingExtractionProvider()
    cortex_base = os.environ.get("CORTEX_OPENAI_BASE_URL") or os.environ.get("CORTEX_BASE_URL")
    return {
        "local_only": True,
        "postgres": {
            "configured": bool(postgres_url),
            "driver_available": _module_available("psycopg"),
            "url_present": bool(postgres_url),
            "pipeline_runtime_importer": True,
        },
        "qdrant": qdrant.dependency_status(),
        "docling": docling.dependency_status(),
        "cortex": {
            "configured": bool(cortex_base),
            "base_url_present": bool(cortex_base),
            "model": os.environ.get("CORTEX_MODEL"),
            "embedding_model": os.environ.get("SUNSHINE_EMBEDDING_MODEL"),
            "ocr_model": os.environ.get("CORTEX_OCR_MODEL") or os.environ.get("SUNSHINE_OCR_FALLBACK_MODEL"),
        },
        "policy": {
            "hosted_third_party_apis_allowed": False,
            "source_files_mutable": False,
        },
    }


def _module_available(module_name: str) -> bool:
    try:
        __import__(module_name)
    except Exception:  # noqa: BLE001 - health check should normalize import failures.
        return False
    return True
