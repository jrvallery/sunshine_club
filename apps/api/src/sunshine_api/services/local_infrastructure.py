"""Local-only infrastructure readiness checks for V2 pipeline dependencies."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sunshine_extraction.config import provider_registry_rows, validate_provider_registry
from sunshine_extraction.providers.extraction import (
    DoclingExtractionProvider,
    MinerUExtractionProvider,
    RAGFlowDeepDocExtractionProvider,
    UnstructuredExtractionProvider,
)
from sunshine_extraction.providers.observability import observability_provider_from_env
from sunshine_extraction.providers.retrieval import QdrantSemanticRetrievalProvider
from sunshine_extraction.providers.vectorstores import QdrantVectorStoreProvider
from sunshine_extraction.services.vector_policy import vector_store_policy_from_env
from sunshine_extraction.services.runtime_policy import pipeline_runtime_policy_from_env


def local_infrastructure_status() -> dict[str, Any]:
    postgres_url = os.environ.get("DATABASE_URL") or os.environ.get("SUNSHINE_DATABASE_URL")
    qdrant = QdrantVectorStoreProvider()
    qdrant_retrieval = QdrantSemanticRetrievalProvider()
    parser_providers = {
        "docling": DoclingExtractionProvider(),
        "mineru": MinerUExtractionProvider(),
        "ragflow_deepdoc": RAGFlowDeepDocExtractionProvider(),
        "unstructured": UnstructuredExtractionProvider(),
    }
    observability = observability_provider_from_env()
    cortex_base = os.environ.get("CORTEX_OPENAI_BASE_URL") or os.environ.get("CORTEX_BASE_URL")
    temporal_address = os.environ.get("TEMPORAL_ADDRESS")
    return {
        "local_only": True,
        "postgres": {
            "configured": bool(postgres_url),
            "driver_available": _module_available("psycopg"),
            "url_present": bool(postgres_url),
            "pipeline_runtime_importer": True,
            "v2_migrations": _migration_status(),
        },
        "vector_store_policy": vector_store_policy_from_env(),
        "runtime_policy": pipeline_runtime_policy_from_env(),
        "qdrant": _qdrant_status(qdrant),
        "qdrant_retrieval": qdrant_retrieval.dependency_status(),
        "docling": parser_providers["docling"].dependency_status(),
        "parser_providers": {name: provider.dependency_status() for name, provider in parser_providers.items()},
        "parser_policy": {
            "ocr_parser_provider": os.environ.get("SUNSHINE_OCR_PARSER_PROVIDER") or os.environ.get("SUNSHINE_DEFAULT_PARSER_PROVIDER") or "docling",
            "text_parser_provider": os.environ.get("SUNSHINE_TEXT_PARSER_PROVIDER") or os.environ.get("SUNSHINE_DEFAULT_PARSER_PROVIDER") or "docling",
            "default_parser_provider": os.environ.get("SUNSHINE_DEFAULT_PARSER_PROVIDER"),
            "allowed": ["current", "docling", "mineru", "ragflow_deepdoc", "unstructured"],
            "hosted_allowed": False,
        },
        "cortex": {
            "configured": bool(cortex_base),
            "base_url_present": bool(cortex_base),
            "model": os.environ.get("CORTEX_MODEL"),
            "embedding_model": os.environ.get("SUNSHINE_EMBEDDING_MODEL"),
            "ocr_model": os.environ.get("CORTEX_OCR_MODEL") or os.environ.get("SUNSHINE_OCR_FALLBACK_MODEL"),
        },
        "model_call_cache": _model_call_cache_status(),
        "temporal": {
            "configured": bool(temporal_address),
            "address": temporal_address,
            "address_reachable": _tcp_reachable(temporal_address),
            "sdk_available": _module_available("temporalio"),
            "worker_registered": _module_available("sunshine_worker.temporal_worker"),
            "task_queue": os.environ.get("SUNSHINE_TEMPORAL_TASK_QUEUE") or "sunshine-pipeline",
        },
        "observability": observability.dependency_status(),
        "provider_registry": {
            "validation": validate_provider_registry(),
            "providers": provider_registry_rows(),
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


def _tcp_reachable(address: str | None, *, timeout_seconds: float = 0.25) -> bool:
    if not address:
        return False
    host, port = _host_port(address)
    if not host or port is None:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _host_port(address: str) -> tuple[str | None, int | None]:
    value = address.strip()
    if not value:
        return None, None
    parsed = urlparse(value if "://" in value else f"tcp://{value}")
    if not parsed.hostname or parsed.port is None:
        return None, None
    return parsed.hostname, parsed.port


def _model_call_cache_status() -> dict[str, Any]:
    configured = os.environ.get("SUNSHINE_MODEL_CACHE_PATH", "").strip()
    path = Path(configured) if configured else None
    return {
        "configured": bool(configured),
        "provider": "sqlite" if configured else "disabled",
        "local_only": True,
        "path": str(path) if path else None,
        "exists": path.exists() if path else False,
        "namespaces": ["embedding", "llm_tag_inspection"],
    }


def _qdrant_status(provider: QdrantVectorStoreProvider) -> dict[str, Any]:
    policy = vector_store_policy_from_env()
    status = provider.dependency_status()
    status["compose_service"] = "qdrant"
    status["compose_file"] = "compose.yaml"
    status["required_for_production"] = True
    status["required_now"] = bool(policy["qdrant_required"])
    status["policy_provider"] = policy["provider"]
    status["policy_reason"] = policy["qdrant_required_reason"]
    return status


def _migration_status() -> dict[str, Any]:
    migration_dir = Path("infra/db/migrations")
    expected = [
        "0001_initial.sql",
        "0002_pipeline_runtime.sql",
        "0003_pipeline_chunks_embeddings.sql",
        "0004_golden_labels_v2.sql",
        "0005_pipeline_run_events_indexes.sql",
        "0006_provider_benchmarks.sql",
        "0007_pipeline_parser_results.sql",
        "0008_model_usage_host.sql",
        "0009_pipeline_provider_selections.sql",
        "0010_pipeline_quality_checks.sql",
        "0011_pipeline_tagging_evidence.sql",
        "0012_pipeline_file_metadata.sql",
    ]
    return {
        "migration_dir": str(migration_dir),
        "expected": expected,
        "present": [name for name in expected if (migration_dir / name).exists()],
        "complete": all((migration_dir / name).exists() for name in expected),
    }
