"""Background process execution and live progress capture for pipeline runs."""

from __future__ import annotations

from pathlib import Path
import asyncio
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

from sunshine_api.dependencies import review_store
from sunshine_api.review_store import ReviewStore
from sunshine_api.services.imports import (
    get_postgres_pipeline_run,
    import_langgraph_output_to_postgres_if_configured,
    record_postgres_pipeline_run_event_if_configured,
    record_postgres_pipeline_run_state_if_configured,
)


from sunshine_api.services.run_reports import _read_live_run_summary, _read_run_summary

_RUN_PROCESSES: dict[int, subprocess.Popen[str]] = {}
_POSTGRES_RUN_PROCESSES: dict[str, subprocess.Popen[str]] = {}
_RUN_PROCESS_LOCK = threading.Lock()
_RUN_PROGRESS_PATTERN = re.compile(r"\[(?P<current>\d+)/(?P<total>\d+)\]")


def _execute_postgres_run(run: dict[str, Any], command: list[str], output_dir: str, import_on_success: bool) -> None:
    run_key = str(run["run_key"])
    try:
        _record_postgres_run_state(run, status="running", summary=_summary_with_backend(run, run.get("summary") or {}))
        _record_postgres_run_event(run_key, status="running", message="Run started.", node="dashboard_run_lifecycle")
        process = subprocess.Popen(
            command,
            cwd=Path.cwd(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            start_new_session=True,
        )
        with _RUN_PROCESS_LOCK:
            _POSTGRES_RUN_PROCESSES[run_key] = process
        _stream_postgres_run_output(run, process, output_dir)
        summary = _read_run_summary(output_dir) or run.get("summary") or {}
        if _postgres_run_status(run_key) == "cancelled":
            _record_postgres_run_event(run_key, status="cancelled", message="Run cancelled.", node="dashboard_run_lifecycle", payload=summary)
            return
        if process.returncode == 0:
            if import_on_success:
                _import_live_outputs_postgres(run, output_dir)
            _record_postgres_run_state(run, status="succeeded", summary=_summary_with_backend(run, summary))
            _record_postgres_run_event(run_key, status="succeeded", message="Run succeeded.", node="dashboard_run_lifecycle", payload=summary)
        else:
            error = f"Command exited {process.returncode}"
            _record_postgres_run_state(run, status="failed", summary=_summary_with_backend(run, summary), error=error)
            _record_postgres_run_event(run_key, status="failed", message=error, node="dashboard_run_lifecycle", payload=summary)
    except Exception as error:  # noqa: BLE001 - background run errors must be visible in the dashboard.
        _record_postgres_run_state(run, status="failed", summary=_summary_with_backend(run, run.get("summary") or {}), error=f"{type(error).__name__}: {error}")
        _record_postgres_run_event(run_key, status="failed", message=f"{type(error).__name__}: {error}", node="dashboard_run_lifecycle")
    finally:
        with _RUN_PROCESS_LOCK:
            _POSTGRES_RUN_PROCESSES.pop(run_key, None)


def cancel_postgres_run_process(run_key: str) -> bool:
    with _RUN_PROCESS_LOCK:
        process = _POSTGRES_RUN_PROCESSES.get(run_key)
    if process is None or process.poll() is not None:
        return False
    try:
        os.killpg(process.pid, 15)
    except ProcessLookupError:
        pass
    except Exception:
        process.terminate()
    return True


def postgres_run_process_is_active(run_key: str) -> bool:
    with _RUN_PROCESS_LOCK:
        process = _POSTGRES_RUN_PROCESSES.get(run_key)
    return process is not None and process.poll() is None


def _postgres_run_status(run_key: str) -> str | None:
    try:
        return str(get_postgres_pipeline_run(run_key=run_key).get("status") or "")
    except Exception:  # noqa: BLE001 - status check should not hide actual process failures.
        return None


def _execute_run(run_id: int, command: list[str], output_dir: str, import_on_success: bool) -> None:
    store: ReviewStore | None = None
    try:
        store = review_store()
        store.mark_pipeline_run_started(run_id)
        run = store.get_pipeline_run(run_id)
        _record_postgres_run_state(run, status="running", summary=_summary_with_backend(run, run.get("summary") or {}))
        process = subprocess.Popen(
            command,
            cwd=Path.cwd(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            start_new_session=True,
        )
        with _RUN_PROCESS_LOCK:
            _RUN_PROCESSES[run_id] = process
        _stream_run_output(store, run_id, process, output_dir)
        summary = _read_run_summary(output_dir)
        if store.get_pipeline_run(run_id)["status"] == "cancelled":
            cancelled_run = store.get_pipeline_run(run_id)
            _record_postgres_run_state(cancelled_run, status="cancelled", summary=summary or cancelled_run.get("summary") or {})
            return
        if process.returncode == 0:
            if import_on_success and (Path(output_dir) / "sample-pipeline-results.jsonl").exists():
                _import_success_outputs(store, run_id, output_dir)
            store.mark_pipeline_run_finished(run_id, status="succeeded", summary=summary)
            finished_run = store.get_pipeline_run(run_id)
            _record_postgres_run_state(finished_run, status="succeeded", summary=_summary_with_backend(finished_run, summary or finished_run.get("summary") or {}))
        else:
            store.mark_pipeline_run_finished(run_id, status="failed", summary=summary, error=f"Command exited {process.returncode}")
            failed_run = store.get_pipeline_run(run_id)
            _record_postgres_run_state(failed_run, status="failed", summary=_summary_with_backend(failed_run, summary or failed_run.get("summary") or {}), error=failed_run.get("error"))
    except Exception as error:  # noqa: BLE001 - background run errors must be captured for the UI.
        if store is not None:
            store.mark_pipeline_run_finished(run_id, status="failed", error=f"{type(error).__name__}: {error}")
            failed_run = store.get_pipeline_run(run_id)
            _record_postgres_run_state(failed_run, status="failed", summary=_summary_with_backend(failed_run, failed_run.get("summary") or {}), error=failed_run.get("error"))
    finally:
        with _RUN_PROCESS_LOCK:
            _RUN_PROCESSES.pop(run_id, None)


def _execute_temporal_batch_run(run_id: int, payload: dict[str, Any], import_on_success: bool) -> None:
    """Execute one dashboard batch run through Temporal instead of a subprocess.

    This keeps the dashboard contract stable while allowing production
    deployments to move durable execution into the worker.
    """

    store: ReviewStore | None = None
    output_dir = str(payload["output_dir"])
    try:
        store = review_store()
        store.mark_pipeline_run_started(run_id)
        run = store.get_pipeline_run(run_id)
        _record_postgres_run_state(run, status="running", summary=_summary_with_backend(run, run.get("summary") or {}))
        result = _start_temporal_batch_workflow(payload, run_key=str(run.get("run_key") or f"run-{run_id}"))
        summary = _read_run_summary(output_dir) or result.get("summary") or {}
        if import_on_success and (Path(output_dir) / "sample-pipeline-results.jsonl").exists():
            _import_success_outputs(store, run_id, output_dir)
        store.mark_pipeline_run_finished(run_id, status="succeeded", summary={**_summary_with_backend(run, summary), "temporal_result": result})
        finished_run = store.get_pipeline_run(run_id)
        _record_postgres_run_state(finished_run, status="succeeded", summary=_summary_with_backend(finished_run, summary or finished_run.get("summary") or {}))
    except Exception as error:  # noqa: BLE001 - background run errors must be captured for the UI.
        if store is not None:
            store.mark_pipeline_run_finished(run_id, status="failed", error=f"{type(error).__name__}: {error}")
            failed_run = store.get_pipeline_run(run_id)
            _record_postgres_run_state(failed_run, status="failed", summary=_summary_with_backend(failed_run, failed_run.get("summary") or {}), error=failed_run.get("error"))


def _start_temporal_batch_workflow(payload: dict[str, Any], *, run_key: str) -> dict[str, Any]:
    return asyncio.run(_start_temporal_batch_workflow_async(payload, run_key=run_key))


async def _start_temporal_batch_workflow_async(payload: dict[str, Any], *, run_key: str) -> dict[str, Any]:
    from temporalio.client import Client
    from sunshine_worker.workflows import BatchPipelineWorkflow

    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    task_queue = os.environ.get("SUNSHINE_TEMPORAL_TASK_QUEUE", "sunshine-pipeline")
    client = await Client.connect(address)
    handle = await client.start_workflow(
        BatchPipelineWorkflow.run,
        payload,
        id=f"sunshine-batch-{run_key}",
        task_queue=task_queue,
    )
    return await handle.result()


def _record_postgres_run_state(run: dict[str, Any], *, status: str, summary: dict[str, Any], error: str | None = None) -> None:
    try:
        record_postgres_pipeline_run_state_if_configured(run=run, status=status, summary=summary, error=error)
    except Exception:  # noqa: BLE001 - SQLite run state and filesystem artifacts remain authoritative for the dev runner.
        return


def _record_postgres_run_event(run_key: str, *, status: str, message: str, node: str | None = None, payload: dict[str, Any] | None = None) -> None:
    try:
        record_postgres_pipeline_run_event_if_configured(
            run_key=run_key,
            status=status,
            message=message,
            node=node,
            payload=payload,
        )
    except Exception:  # noqa: BLE001 - event capture must not break the run.
        return


def _summary_with_backend(run: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    metadata = run.get("run_metadata") if isinstance(run.get("run_metadata"), dict) else {}
    execution_backend = run.get("execution_backend") or metadata.get("execution_backend") or "subprocess"
    return {**summary, "execution_backend": execution_backend}


def _import_success_outputs_postgres(run: dict[str, Any], output_dir: str) -> None:
    run_key = str(run["run_key"])
    try:
        postgres_result = import_langgraph_output_to_postgres_if_configured(
            output_dir,
            run_key=run_key,
            preset_key=run.get("preset_key"),
        )
        status = "imported" if postgres_result.get("import_status") == "imported" else "warning"
        message = "Imported run artifacts into Postgres." if status == "imported" else "Postgres import skipped or incomplete."
        _record_postgres_run_event(run_key, status=status, message=message, node="dashboard_import", payload=postgres_result)
    except Exception as error:  # noqa: BLE001 - final status should expose import failure.
        _record_postgres_run_event(
            run_key,
            status="failed",
            message=f"Postgres import failed: {type(error).__name__}: {error}",
            node="dashboard_import",
        )


def _import_live_outputs_postgres(run: dict[str, Any], output_dir: str) -> None:
    aggregate_dir = _build_live_import_dir(Path(output_dir))
    if aggregate_dir is None:
        return
    _import_success_outputs_postgres(run, str(aggregate_dir))


def _build_live_import_dir(output_dir: Path) -> Path | None:
    graph_runs_dir = output_dir / "graph-runs"
    if not graph_runs_dir.exists():
        return output_dir if (output_dir / "sample-pipeline-results.jsonl").exists() else None
    run_dirs = sorted(path for path in graph_runs_dir.iterdir() if path.is_dir() and (path / "sample-pipeline-results.jsonl").exists())
    if not run_dirs:
        return None
    aggregate_dir = output_dir / ".postgres-live-import"
    aggregate_dir.mkdir(parents=True, exist_ok=True)
    jsonl_names = sorted({path.name for run_dir in run_dirs for path in run_dir.glob("*.jsonl")})
    for name in jsonl_names:
        with (aggregate_dir / name).open("w", encoding="utf-8") as output_file:
            for run_dir in run_dirs:
                input_path = run_dir / name
                if input_path.exists():
                    with input_path.open("r", encoding="utf-8") as input_file:
                        for line in input_file:
                            if line.strip():
                                output_file.write(line if line.endswith("\n") else f"{line}\n")
    artifacts: list[dict[str, Any]] = []
    first_metadata: dict[str, Any] = {}
    for run_dir in run_dirs:
        manifest_path = run_dir / "artifact-manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                manifest = {}
            if isinstance(manifest.get("artifacts"), list):
                artifacts.extend(row for row in manifest["artifacts"] if isinstance(row, dict))
        metadata_path = run_dir / "graph-run-metadata.json"
        if not first_metadata and metadata_path.exists():
            try:
                first_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                first_metadata = {}
    (aggregate_dir / "artifact-manifest.json").write_text(json.dumps({"artifacts": artifacts}, sort_keys=True), encoding="utf-8")
    (aggregate_dir / "graph-run-metadata.json").write_text(json.dumps(first_metadata, sort_keys=True), encoding="utf-8")
    return aggregate_dir


def _stream_postgres_run_output(run: dict[str, Any], process: subprocess.Popen[str], output_dir: str) -> None:
    run_key = str(run["run_key"])
    selector = selectors.DefaultSelector()
    if process.stdout is not None:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    if process.stderr is not None:
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    last_heartbeat = time.monotonic()
    try:
        while selector.get_map():
            for key, _mask in selector.select(timeout=1.0):
                stream = key.fileobj
                line = stream.readline()
                if line == "":
                    selector.unregister(stream)
                    continue
                message = line.rstrip()
                if not message:
                    continue
                level = "failed" if key.data == "stderr" and _is_error_log(message) else "running"
                payload = _progress_payload_from_message(message)
                _record_postgres_run_event(run_key, status=level, message=message[-4000:], node="pipeline_stdout", payload=payload)
                if payload:
                    summary = {
                        **(run.get("summary") or {}),
                        "processed_count": payload["current"],
                        "selected_sample_count": payload["total"],
                        "progress_ratio": payload["current"] / payload["total"] if payload["total"] else None,
                    }
                    run["summary"] = summary
                    _record_postgres_run_state(run, status="running", summary=summary)
            if process.poll() is not None:
                for key in list(selector.get_map().values()):
                    line = key.fileobj.readline()
                    while line:
                        message = line.rstrip()
                        if message:
                            level = "failed" if key.data == "stderr" and _is_error_log(message) else "running"
                            payload = _progress_payload_from_message(message)
                            _record_postgres_run_event(run_key, status=level, message=message[-4000:], node="pipeline_stdout", payload=payload)
                        line = key.fileobj.readline()
                    selector.unregister(key.fileobj)
                break
            if time.monotonic() - last_heartbeat >= 15:
                summary = _read_live_run_summary(output_dir, run.get("summary") or {})
                if summary:
                    run["summary"] = summary
                    _record_postgres_run_state(run, status="running", summary=summary)
                    _import_live_outputs_postgres(run, output_dir)
                _record_postgres_run_event(run_key, status="running", message="Run still active.", node="dashboard_heartbeat", payload=summary)
                last_heartbeat = time.monotonic()
    finally:
        selector.close()


def _record_postgres_run_progress(store: ReviewStore, run_id: int, summary: dict[str, Any]) -> None:
    try:
        run = store.get_pipeline_run(run_id)
    except Exception:  # noqa: BLE001 - live progress mirroring must not break stream capture.
        return
    _record_postgres_run_state(run, status="running", summary=summary)


def _import_success_outputs(store: ReviewStore, run_id: int, output_dir: str) -> None:
    run = store.get_pipeline_run(run_id)
    sqlite_result = store.import_langgraph_output(output_dir, sample_routed_per_bucket=0, run_id=run_id)
    postgres_result: dict[str, Any]
    try:
        postgres_result = import_langgraph_output_to_postgres_if_configured(
            output_dir,
            run_key=str(run["run_key"]),
            preset_key=run.get("preset_key"),
        )
        postgres_level = "info" if postgres_result.get("import_status") != "skipped" else "warning"
    except Exception as error:  # noqa: BLE001 - import failures are audit events; artifacts remain on disk.
        postgres_result = {
            "import_status": "failed",
            "importer": "postgres_runtime",
            "error": f"{type(error).__name__}: {error}",
        }
        postgres_level = "error"
    with store._connect() as connection:
        store.add_pipeline_run_event(
            connection,
            run_id,
            level="info",
            message="Imported run artifacts into legacy dashboard store.",
            payload=sqlite_result,
        )
        store.add_pipeline_run_event(
            connection,
            run_id,
            level=postgres_level,
            message="Imported run artifacts into Postgres V2 runtime." if postgres_result.get("import_status") == "imported" else "Postgres V2 runtime import skipped or failed.",
            payload=postgres_result,
        )


def _stream_run_output(store: ReviewStore, run_id: int, process: subprocess.Popen[str], output_dir: str) -> None:
    selector = selectors.DefaultSelector()
    if process.stdout is not None:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    if process.stderr is not None:
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    last_heartbeat = time.monotonic()
    try:
        while selector.get_map():
            for key, _mask in selector.select(timeout=1.0):
                stream = key.fileobj
                line = stream.readline()
                if line == "":
                    selector.unregister(stream)
                    continue
                message = line.rstrip()
                if not message:
                    continue
                level = "error" if key.data == "stderr" and _is_error_log(message) else "info"
                payload = _progress_payload_from_message(message)
                with store._connect() as connection:
                    store.add_pipeline_run_event(connection, run_id, level=level, message=message[-4000:], payload=payload)
                if payload:
                    summary = {
                        "processed_count": payload["current"],
                        "selected_sample_count": payload["total"],
                        "progress_ratio": payload["current"] / payload["total"] if payload["total"] else None,
                    }
                    store.update_pipeline_run_progress(run_id, summary)
                    _record_postgres_run_progress(store, run_id, summary)
            if process.poll() is not None:
                for key in list(selector.get_map().values()):
                    line = key.fileobj.readline()
                    while line:
                        message = line.rstrip()
                        if message:
                            level = "error" if key.data == "stderr" and _is_error_log(message) else "info"
                            payload = _progress_payload_from_message(message)
                            with store._connect() as connection:
                                store.add_pipeline_run_event(connection, run_id, level=level, message=message[-4000:], payload=payload)
                        line = key.fileobj.readline()
                    selector.unregister(key.fileobj)
                break
            if time.monotonic() - last_heartbeat >= 15:
                summary = _read_live_run_summary(output_dir, store.get_pipeline_run(run_id).get("summary") or {})
                if summary:
                    store.update_pipeline_run_progress(run_id, summary)
                    _record_postgres_run_progress(store, run_id, summary)
                with store._connect() as connection:
                    store.add_pipeline_run_event(connection, run_id, level="info", message="Run still active.", payload=summary)
                last_heartbeat = time.monotonic()
    finally:
        selector.close()


def _is_error_log(message: str) -> bool:
    lowered = message.lower()
    return "error" in lowered or "traceback" in lowered or "exception" in lowered or "failed" in lowered


def _progress_payload_from_message(message: str) -> dict[str, Any]:
    match = _RUN_PROGRESS_PATTERN.search(message)
    if not match:
        return {}
    current = int(match.group("current"))
    total = int(match.group("total"))
    return {"current": current, "total": total, "progress_ratio": current / total if total else None}
