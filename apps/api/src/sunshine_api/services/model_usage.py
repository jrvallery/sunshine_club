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


from sunshine_api.services.run_reports import _read_jsonl_file


def _read_model_usage_artifact(output_dir: Path, *, run_id: int) -> list[dict[str, Any]]:
    rows = _read_jsonl_file(output_dir / "sample-model-usage.jsonl")
    for index, row in enumerate(rows, start=1):
        row.setdefault("id", index)
        row.setdefault("run_id", run_id)
        row.setdefault("purpose", "unknown")
        row.setdefault("provider", "unknown")
        row.setdefault("model", "unknown")
        row.setdefault("status", "unknown")
    return rows


def _model_usage_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "total_calls": len(rows),
        "failed_calls": sum(1 for row in rows if str(row.get("status") or "").lower() not in {"ok", "success", "succeeded", "completed"}),
        "external_calls": sum(1 for row in rows if _is_external_model_call(row)),
        "local_calls": sum(1 for row in rows if not _is_external_model_call(row)),
        "runtime_ms": _sum_numeric(rows, "runtime_ms"),
        "input_tokens": _sum_numeric(rows, "input_tokens"),
        "output_tokens": _sum_numeric(rows, "output_tokens"),
        "total_tokens": _sum_numeric(rows, "total_tokens"),
        "estimated_external_cost_usd": round(
            sum(float(row.get("estimated_cost_usd") or 0) for row in rows if _is_external_model_call(row)),
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
    cost_basis = str(row.get("cost_basis") or "").lower()
    provider = str(row.get("provider") or "").lower()
    if cost_basis == "external":
        return True
    if cost_basis == "local":
        return False
    return provider in {"openai", "gemini", "google", "anthropic"}


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
        bucket["calls"] += 1
        if str(row.get("status") or "").lower() not in {"ok", "success", "succeeded", "completed"}:
            bucket["failed_calls"] += 1
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

