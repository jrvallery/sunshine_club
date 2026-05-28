"""Model usage artifact parsing and cost/runtime summaries."""

from __future__ import annotations

from pathlib import Path
import json
import os
import re
import selectors
import sqlite3
import subprocess
import threading
import time
from datetime import UTC, datetime
from typing import Any

from sunshine_api.review_store import ReviewStore


from sunshine_api.services.run_reports import _read_run_jsonl_with_live_fallback


def _read_model_usage_artifact(output_dir: Path, *, run_id: int) -> list[dict[str, Any]]:
    rows = _read_run_jsonl_with_live_fallback(output_dir, "sample-model-usage.jsonl")
    if not rows:
        rows = _synthesize_model_usage_from_artifacts(output_dir)
    for index, row in enumerate(rows, start=1):
        row.setdefault("id", index)
        row.setdefault("run_id", run_id)
        row.setdefault("purpose", "unknown")
        row.setdefault("provider", "unknown")
        row.setdefault("model", "unknown")
        row.setdefault("status", "unknown")
    return rows


def _model_usage_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    external_rows = [row for row in rows if _is_external_model_call(row)]
    local_rows = [row for row in rows if _model_cost_basis(row) == "local"]
    placeholder_rows = [row for row in rows if _model_cost_basis(row) == "placeholder"]
    unknown_cost_basis_rows = [row for row in rows if _model_cost_basis(row) == "unknown"]
    summary = {
        "total_calls": _sum_call_counts(rows),
        "total_model_usage_rows": len(rows),
        "failed_calls": sum(
            _model_call_count(row)
            for row in rows
            if str(row.get("status") or "").lower() not in {"ok", "success", "succeeded", "completed", "skipped"}
        ),
        "external_calls": _sum_call_counts(external_rows),
        "local_calls": _sum_call_counts(local_rows),
        "placeholder_calls": _sum_call_counts(placeholder_rows),
        "unknown_cost_basis_calls": _sum_call_counts(unknown_cost_basis_rows),
        "cost_basis_completeness_rate": ((_sum_call_counts(rows) - _sum_call_counts(unknown_cost_basis_rows)) / _sum_call_counts(rows)) if _sum_call_counts(rows) else None,
        "runtime_ms": _sum_numeric(rows, "runtime_ms"),
        "input_tokens": _sum_numeric(rows, "input_tokens"),
        "output_tokens": _sum_numeric(rows, "output_tokens"),
        "total_tokens": _sum_numeric(rows, "total_tokens"),
        "unknown_external_cost_calls": sum(_model_call_count(row) for row in external_rows if row.get("estimated_cost_usd") is None),
        "estimated_external_cost_usd": round(
            sum(float(row.get("estimated_cost_usd") or 0) for row in external_rows),
            6,
        ),
    }
    return {
        "summary": summary,
        "by_provider_model": _model_usage_breakdowns(rows, ["provider", "model"]),
        "by_purpose": _model_usage_breakdowns(rows, ["purpose"]),
        "by_status": _count_values(rows, "status"),
        "calls": rows[:500],
    }


def _is_external_model_call(row: dict[str, Any]) -> bool:
    return _model_cost_basis(row) == "external"


def _sum_call_counts(rows: list[dict[str, Any]]) -> int:
    return sum(_model_call_count(row) for row in rows)


def _model_call_count(row: dict[str, Any]) -> int:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    raw_call_count = metadata.get("call_count")
    if raw_call_count is None:
        return 1
    try:
        return max(0, int(raw_call_count))
    except (TypeError, ValueError):
        return 1


def _model_cost_basis(row: dict[str, Any]) -> str:
    cost_basis = str(row.get("cost_basis") or "").lower()
    provider = str(row.get("provider") or "").lower()
    if cost_basis == "external":
        return "external"
    if cost_basis == "local":
        return "local"
    if cost_basis == "placeholder":
        return "placeholder"
    if provider in {"openai", "gemini", "google", "anthropic"}:
        return "external"
    if provider in {"cortex", "vllm", "local", "tesseract"}:
        return "local"
    if provider == "placeholder":
        return "placeholder"
    return "unknown"


def _synthesize_model_usage_from_artifacts(output_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend(_synthesize_ocr_usage(output_dir))
    rows.extend(_synthesize_llm_tag_usage(output_dir))
    rows.extend(_synthesize_embedding_usage(output_dir))
    return rows


def _synthesize_ocr_usage(output_dir: Path) -> list[dict[str, Any]]:
    page_rows = _read_run_jsonl_with_live_fallback(output_dir, "sample-ocr-pages.jsonl")
    rows = []
    for page in page_rows:
        warning = _first_warning_with_prefix(page.get("warnings", []), "ocr_fallback_used:")
        purpose = "ocr_fallback"
        prefix = "ocr_fallback_used:"
        if not warning:
            warning = _first_warning_with_prefix(page.get("warnings", []), "ocr_model_used:")
            purpose = "ocr"
            prefix = "ocr_model_used:"
        if not warning:
            engine = str(page.get("ocr_engine") or "")
            if not engine or engine == "tesseract":
                continue
            warning = f"ocr_model_used:{engine}"
            purpose = "ocr"
            prefix = "ocr_model_used:"
        provider, model = _provider_model_from_engine(warning.removeprefix(prefix))
        rows.append(
            {
                "source_path": page.get("source_path"),
                "relative_path": page.get("relative_path"),
                "node": "ocr_artifact_inference",
                "purpose": purpose,
                "provider": provider,
                "model": model,
                "status": "ok" if page.get("ocr_status") == "ok" else str(page.get("ocr_status") or "unknown"),
                "runtime_ms": _seconds_to_ms(page.get("seconds")),
                "cost_basis": "external" if _provider_is_external(provider) else "local",
                "metadata": {"inferred_from": "sample-ocr-pages.jsonl", "page_number": page.get("page_number")},
            }
        )
    if rows:
        return rows

    result_rows = _read_run_jsonl_with_live_fallback(output_dir, "sample-pipeline-results.jsonl")
    for result in result_rows:
        warning = _first_warning_with_prefix(result.get("warnings", []), "ocr_fallback_used:")
        if not warning:
            continue
        provider, model = _provider_model_from_engine(warning.removeprefix("ocr_fallback_used:"))
        rows.append(
            {
                "source_path": result.get("source_path"),
                "relative_path": result.get("relative_path"),
                "node": "pipeline_result_inference",
                "purpose": "ocr_fallback",
                "provider": provider,
                "model": model,
                "status": "unknown",
                "cost_basis": "external" if _provider_is_external(provider) else "local",
                "metadata": {"inferred_from": "sample-pipeline-results.jsonl"},
            }
        )
    return rows


def _synthesize_llm_tag_usage(output_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for inspection in _read_run_jsonl_with_live_fallback(output_dir, "sample-llm-tag-inspections.jsonl"):
        provider = str(inspection.get("provider") or "unknown")
        status = str(inspection.get("llm_status") or "unknown")
        if provider == "disabled" and status == "skipped":
            continue
        rows.append(
            {
                "source_path": inspection.get("source_path"),
                "relative_path": inspection.get("relative_path"),
                "node": "llm_tag_inspection_artifact",
                "purpose": "tag_inspection",
                "provider": provider,
                "model": str(inspection.get("model") or "unknown"),
                "status": "ok" if status == "inspected" else status,
                "cost_basis": "external" if _provider_is_external(provider) else "local",
                "error": inspection.get("warning"),
                "metadata": {"inferred_from": "sample-llm-tag-inspections.jsonl"},
            }
        )
    return rows


def _synthesize_embedding_usage(output_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for embedding in _read_run_jsonl_with_live_fallback(output_dir, "sample-embeddings.jsonl"):
        provider = str(embedding.get("embedding_provider") or "unknown")
        rows.append(
            {
                "source_path": embedding.get("source_path"),
                "relative_path": embedding.get("relative_path"),
                "node": "embedding_artifact",
                "purpose": "chunk_embedding",
                "provider": provider,
                "model": str(embedding.get("embedding_model") or "unknown"),
                "status": str(embedding.get("embedding_status") or "unknown"),
                "cost_basis": "external" if _provider_is_external(provider) else "local",
                "metadata": {
                    "inferred_from": "sample-embeddings.jsonl",
                    "chunk_id": embedding.get("chunk_id"),
                    "embedding_dimensions": embedding.get("embedding_dimensions"),
                },
            }
        )
    return rows


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


def _provider_is_external(provider: str) -> bool:
    return provider.lower() in {"openai", "gemini", "google", "anthropic"}


def _seconds_to_ms(value: Any) -> int | None:
    if not isinstance(value, int | float):
        return None
    return round(float(value) * 1000)


def _model_usage_breakdowns(rows: list[dict[str, Any]], fields: list[str]) -> dict[str, dict[str, Any]]:
    breakdown: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = " / ".join(str(row.get(field) or "unknown") for field in fields)
        bucket = breakdown.setdefault(
            key,
            {
                "calls": 0,
                "failed_calls": 0,
                "runtime_ms": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "estimated_external_cost_usd": 0.0,
            },
        )
        call_count = _model_call_count(row)
        bucket["calls"] += call_count
        if str(row.get("status") or "").lower() not in {"ok", "success", "succeeded", "completed", "skipped"}:
            bucket["failed_calls"] += call_count
        bucket["runtime_ms"] += int(row.get("runtime_ms") or 0)
        bucket["input_tokens"] += int(row.get("input_tokens") or 0)
        bucket["output_tokens"] += int(row.get("output_tokens") or 0)
        bucket["total_tokens"] += int(row.get("total_tokens") or 0)
        if _is_external_model_call(row):
            bucket["estimated_external_cost_usd"] = round(
                float(bucket["estimated_external_cost_usd"]) + float(row.get("estimated_cost_usd") or 0),
                6,
            )
    return breakdown


def _sum_numeric(rows: list[dict[str, Any]], field: str) -> int:
    return sum(int(row.get(field) or 0) for row in rows)


def _count_values(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(field) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _count_list_values(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        values = row.get(field) or []
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        for value in values:
            key = str(value or "unknown")
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
