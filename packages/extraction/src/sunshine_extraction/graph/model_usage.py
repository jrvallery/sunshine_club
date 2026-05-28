"""Model-usage row helpers shared by graph nodes."""

from __future__ import annotations

import time
from typing import Any

from sunshine_extraction.embeddings import EmbeddingProvider
from sunshine_extraction.graph.node_utils import _llm_inspection_warnings
from sunshine_extraction.graph.state import DocumentPipelineState


def _ocr_model_usage_rows(state: DocumentPipelineState, pages: list[dict[str, Any]], *, node: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in pages:
        warning = _first_warning_with_prefix(page.get("warnings", []), "ocr_fallback_used:")
        if not warning:
            continue
        provider, model = _provider_model_from_engine(warning.removeprefix("ocr_fallback_used:"))
        rows.append(
            _model_usage_row(
                state,
                node=node,
                purpose="ocr_fallback",
                provider=provider,
                model=model,
                status="ok" if page.get("ocr_status") == "ok" else str(page.get("ocr_status") or "unknown"),
                runtime_ms=_seconds_to_ms(page.get("seconds")),
                cost_basis=_cost_basis(provider),
                metadata={
                    "page_number": page.get("page_number"),
                    "page_count": page.get("page_count"),
                    "ocr_engine": page.get("ocr_engine"),
                    "cost_estimate": "unavailable",
                },
            )
        )
    return rows

def _embedding_model_usage_row(
    state: DocumentPipelineState,
    provider: EmbeddingProvider,
    *,
    node: str,
    purpose: str,
    status: str,
    call_count: int,
    started: float,
    error: str | None = None,
) -> dict[str, Any] | None:
    if call_count <= 0:
        return None
    provider_name = str(getattr(provider, "provider_name", "") or provider.__class__.__name__.replace("EmbeddingProvider", "").lower() or "embedding")
    if provider_name == "placeholder":
        provider_name = "placeholder"
    return _model_usage_row(
        state,
        node=node,
        purpose=purpose,
        provider=provider_name,
        model=str(getattr(provider, "model", "unknown")),
        status=status,
        runtime_ms=round((time.monotonic() - started) * 1000),
        error=error,
        cost_basis=_cost_basis(provider_name),
        metadata={
            "call_count": call_count,
            "embedding_dimensions": getattr(provider, "dimensions", None),
            "cost_estimate": "unavailable",
        },
    )

def _llm_tag_model_usage_row(state: DocumentPipelineState, inspection: dict[str, Any], *, started: float) -> dict[str, Any] | None:
    provider = str(inspection.get("provider") or "unknown")
    status = str(inspection.get("llm_status") or "unknown")
    if provider == "disabled" and status == "skipped":
        return None
    warnings = _llm_inspection_warnings(inspection)
    return _model_usage_row(
        state,
        node="inspect_tags_with_llm",
        purpose="tag_inspection",
        provider=provider,
        model=str(inspection.get("model") or "unknown"),
        status="ok" if status == "inspected" else status,
        runtime_ms=round((time.monotonic() - started) * 1000),
        input_tokens=_optional_int(inspection.get("input_tokens")),
        output_tokens=_optional_int(inspection.get("output_tokens")),
        total_tokens=_optional_int(inspection.get("total_tokens")),
        estimated_cost_usd=_optional_float(inspection.get("estimated_cost_usd")),
        error=";".join(warnings) or None,
        cost_basis=_cost_basis(provider),
        metadata={"cost_estimate": "unavailable"},
    )

def _model_usage_row(
    state: DocumentPipelineState,
    *,
    node: str,
    purpose: str,
    provider: str,
    model: str,
    status: str,
    runtime_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    estimated_cost_usd: float | None = None,
    error: str | None = None,
    cost_basis: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "source_path": state.get("source_path"),
        "relative_path": state.get("relative_path"),
        "node": node,
        "purpose": purpose,
        "provider": provider,
        "model": model,
        "status": status,
        "runtime_ms": runtime_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": estimated_cost_usd,
        "cost_basis": cost_basis or _cost_basis(provider),
        "error": error,
        "metadata": metadata or {},
    }

def _first_warning_with_prefix(warnings: Any, prefix: str) -> str | None:
    if isinstance(warnings, str):
        warnings = [warnings]
    if not isinstance(warnings, list):
        return None
    for warning in warnings:
        if isinstance(warning, str) and warning.startswith(prefix):
            return warning
    return None

def _provider_model_from_engine(engine: str) -> tuple[str, str]:
    provider, separator, model = engine.partition(":")
    if not separator:
        return provider or "unknown", "unknown"
    return provider or "unknown", model or "unknown"

def _cost_basis(provider: str) -> str:
    normalized = provider.lower()
    if normalized in {"placeholder", "local-placeholder"}:
        return "placeholder"
    return "external" if normalized in {"openai", "gemini", "google", "anthropic"} else "local"

def _seconds_to_ms(value: Any) -> int | None:
    if not isinstance(value, int | float):
        return None
    return round(float(value) * 1000)

def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    return None

def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
