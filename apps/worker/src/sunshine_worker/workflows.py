"""Temporal workflow definitions for Sunshine pipeline execution."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from sunshine_worker.activities import run_single_file_pipeline_activity


@workflow.defn
class SingleFilePipelineWorkflow:
    """Durable wrapper around the single-file LangGraph pipeline."""

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await workflow.execute_activity(
            run_single_file_pipeline_activity,
            payload,
            start_to_close_timeout=timedelta(hours=float(payload.get("timeout_hours") or 2)),
            retry_policy=RetryPolicy(maximum_attempts=int(payload.get("maximum_attempts") or 1)),
        )


__all__ = ["SingleFilePipelineWorkflow"]
