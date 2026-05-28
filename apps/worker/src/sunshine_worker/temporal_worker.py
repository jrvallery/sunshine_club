"""Temporal worker registration for Sunshine workflow activities."""

from __future__ import annotations

import os

from temporalio.client import Client
from temporalio.worker import Worker

from sunshine_worker.activities import run_single_file_pipeline_activity
from sunshine_worker.workflows import SingleFilePipelineWorkflow


DEFAULT_TEMPORAL_ADDRESS = "localhost:7233"
DEFAULT_TASK_QUEUE = "sunshine-pipeline"


async def run_worker(*, address: str | None = None, task_queue: str | None = None) -> None:
    client = await Client.connect(address or os.environ.get("TEMPORAL_ADDRESS") or DEFAULT_TEMPORAL_ADDRESS)
    worker = Worker(
        client,
        task_queue=task_queue or os.environ.get("SUNSHINE_TEMPORAL_TASK_QUEUE") or DEFAULT_TASK_QUEUE,
        workflows=[SingleFilePipelineWorkflow],
        activities=[run_single_file_pipeline_activity],
    )
    await worker.run()
