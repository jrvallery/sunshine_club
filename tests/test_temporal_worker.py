from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from sunshine_worker.activities import run_single_file_pipeline_activity
from sunshine_worker.temporal_worker import DEFAULT_TASK_QUEUE, run_worker
from sunshine_worker.workflows import SingleFilePipelineWorkflow


def test_single_file_activity_wraps_langgraph_runtime(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run_document_graph(input_file: str, **kwargs: Any) -> dict[str, Any]:
        captured["input_file"] = input_file
        captured["kwargs"] = kwargs
        return {"final_result": {"route_status": "route_candidate", "source_path": kwargs["source_path"]}}

    monkeypatch.setattr("sunshine_worker.activities.load_pipeline_env", lambda: None)
    monkeypatch.setattr("sunshine_worker.activities.run_document_graph", fake_run_document_graph)

    result = asyncio.run(
        run_single_file_pipeline_activity(
            {
                "input_file": "/mnt/sunshine/file.pdf",
                "output_dir": str(tmp_path),
                "source_path": "/source/file.pdf",
                "relative_path": "Sunshine/file.pdf",
                "taxonomy_path": "taxonomy.json",
                "retry_attempts": 2,
            }
        )
    )

    assert captured["input_file"] == "/mnt/sunshine/file.pdf"
    assert captured["kwargs"]["taxonomy_path"] == "taxonomy.json"
    assert captured["kwargs"]["retry_attempts"] == 2
    assert result["ok"] is True
    assert result["final_result"]["route_status"] == "route_candidate"
    assert result["graph_result_path"] == str(tmp_path / "graph-result.json")


def test_temporal_worker_registers_pipeline_workflow_and_activity(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeClient:
        @classmethod
        async def connect(cls, address: str) -> str:
            captured["address"] = address
            return "client"

    class FakeWorker:
        def __init__(self, client: str, *, task_queue: str, workflows: list[Any], activities: list[Any]) -> None:
            captured["client"] = client
            captured["task_queue"] = task_queue
            captured["workflows"] = workflows
            captured["activities"] = activities

        async def run(self) -> None:
            captured["ran"] = True

    monkeypatch.setattr("sunshine_worker.temporal_worker.Client", FakeClient)
    monkeypatch.setattr("sunshine_worker.temporal_worker.Worker", FakeWorker)

    asyncio.run(run_worker(address="temporal:7233"))

    assert captured["address"] == "temporal:7233"
    assert captured["task_queue"] == DEFAULT_TASK_QUEUE
    assert captured["workflows"] == [SingleFilePipelineWorkflow]
    assert captured["activities"] == [run_single_file_pipeline_activity]
    assert captured["ran"] is True
