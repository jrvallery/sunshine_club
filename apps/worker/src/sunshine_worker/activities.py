"""Temporal activities for Sunshine pipeline execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from temporalio import activity

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


__all__ = ["run_single_file_pipeline_activity"]
