"""Runtime and artifact-retention policy for V2 pipeline runs."""

from __future__ import annotations

import os
from typing import Any


def pipeline_runtime_policy_from_env() -> dict[str, Any]:
    latency_target_ms = _positive_int(os.environ.get("SUNSHINE_SINGLE_FILE_LATENCY_TARGET_MS"), default=120_000)
    latency_hard_limit_ms = _positive_int(os.environ.get("SUNSHINE_SINGLE_FILE_LATENCY_HARD_LIMIT_MS"), default=300_000)
    raw_provider_max_bytes = _positive_int(os.environ.get("SUNSHINE_RAW_PROVIDER_ARTIFACT_MAX_BYTES"), default=25 * 1024 * 1024)
    raw_provider_inline_preview_bytes = _positive_int(os.environ.get("SUNSHINE_RAW_PROVIDER_INLINE_PREVIEW_BYTES"), default=64 * 1024)
    return {
        "single_file_latency_target_ms": latency_target_ms,
        "single_file_latency_hard_limit_ms": max(latency_target_ms, latency_hard_limit_ms),
        "raw_provider_artifact_max_bytes": raw_provider_max_bytes,
        "raw_provider_inline_preview_bytes": min(raw_provider_inline_preview_bytes, raw_provider_max_bytes),
        "raw_provider_storage": "artifact_file_by_run",
        "source_files_mutable": False,
        "hosted_third_party_apis_allowed": False,
        "local_only": True,
    }


def runtime_summary(*, started_monotonic: float, finished_monotonic: float, policy: dict[str, Any]) -> dict[str, Any]:
    runtime_ms = round((finished_monotonic - started_monotonic) * 1000)
    target_ms = int(policy["single_file_latency_target_ms"])
    hard_limit_ms = int(policy["single_file_latency_hard_limit_ms"])
    return {
        "runtime_ms": runtime_ms,
        "latency_target_ms": target_ms,
        "latency_hard_limit_ms": hard_limit_ms,
        "latency_status": "ok" if runtime_ms <= target_ms else ("slow" if runtime_ms <= hard_limit_ms else "over_hard_limit"),
        "policy": policy,
    }


def _positive_int(value: str | None, *, default: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except ValueError:
        return default
    return parsed if parsed > 0 else default
