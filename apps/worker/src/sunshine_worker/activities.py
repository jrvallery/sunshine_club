"""Temporal activities for Sunshine pipeline execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from temporalio import activity

from sunshine_extraction.graph.batch import run_document_batch
from sunshine_extraction.graph.runtime import run_document_graph
from sunshine_extraction.graph.utils import _json_safe
from sunshine_extraction.services.env import load_pipeline_env


@activity.defn
async def run_single_file_pipeline_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one local file through the LangGraph document pipeline."""

    load_pipeline_env()
    input_file = payload["input_file"]
    output_dir = payload["output_dir"]
    kwargs: dict[str, Any] = {
        "output_dir": output_dir,
        "source_path": payload.get("source_path"),
        "relative_path": payload.get("relative_path"),
        "checkpoint_path": payload.get("checkpoint_path"),
        "thread_id": payload.get("thread_id"),
        "retry_attempts": int(payload.get("retry_attempts") or 1),
        "retry_delay_seconds": float(payload.get("retry_delay_seconds") or 0),
    }
    taxonomy_path = payload.get("taxonomy_path") or payload.get("taxonomy")
    if taxonomy_path:
        kwargs["taxonomy_path"] = taxonomy_path
    result = run_document_graph(input_file, **kwargs)
    output_path = Path(output_dir)
    return {
        "ok": True,
        "input_file": str(input_file),
        "output_dir": str(output_path),
        "final_result": _json_safe(result.get("final_result", {})),
        "graph_result_path": str(output_path / "graph-result.json"),
        "graph_audit_events_path": str(output_path / "graph-audit-events.jsonl"),
    }


@activity.defn
async def run_batch_pipeline_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Run a local QA/sample batch through the LangGraph document pipeline."""

    load_pipeline_env()
    kwargs: dict[str, Any] = {
        "output_dir": payload["output_dir"],
        "corrected_path": payload.get("corrected_path"),
        "plan_path": payload.get("plan_path"),
        "taxonomy_path": payload.get("taxonomy_path"),
        "limit": payload.get("limit"),
        "semantic_index_path": payload.get("semantic_index_path"),
        "progress": bool(payload.get("progress", False)),
        "checkpoint_path": payload.get("checkpoint_path"),
        "retry_attempts": int(payload.get("retry_attempts") or 1),
        "retry_delay_seconds": float(payload.get("retry_delay_seconds") or 0),
        "max_concurrency": int(payload.get("max_concurrency") or 1),
        "rate_limit_seconds": float(payload.get("rate_limit_seconds") or 0),
    }
    clean_kwargs = {key: value for key, value in kwargs.items() if value is not None}
    summary = run_document_batch(payload["input_root"], **clean_kwargs)
    output_path = Path(payload["output_dir"])
    return {
        "ok": True,
        "input_root": str(payload["input_root"]),
        "output_dir": str(output_path),
        "summary": _json_safe(summary),
        "graph_batch_summary_path": str(output_path / "graph-batch-summary.json"),
        "artifact_manifest_path": str(output_path / "artifact-manifest.json"),
    }


__all__ = ["run_batch_pipeline_activity", "run_single_file_pipeline_activity"]
