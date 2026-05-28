"""Background process execution and live progress capture for pipeline runs."""

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

from sunshine_api.dependencies import review_store
from sunshine_api.review_store import ReviewStore
from sunshine_api.services.imports import import_langgraph_output_to_postgres_if_configured, record_postgres_pipeline_run_state_if_configured


from sunshine_api.services.run_reports import _read_live_run_summary, _read_run_summary

_RUN_PROCESSES: dict[int, subprocess.Popen[str]] = {}
_RUN_PROCESS_LOCK = threading.Lock()
_RUN_PROGRESS_PATTERN = re.compile(r"\[(?P<current>\d+)/(?P<total>\d+)\]")


def _execute_run(run_id: int, command: list[str], output_dir: str, import_on_success: bool) -> None:
    store: ReviewStore | None = None
    try:
        store = review_store()
        store.mark_pipeline_run_started(run_id)
        run = store.get_pipeline_run(run_id)
        _record_postgres_run_state(run, status="running", summary=run.get("summary") or {})
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
            _record_postgres_run_state(finished_run, status="succeeded", summary=summary or finished_run.get("summary") or {})
        else:
            store.mark_pipeline_run_finished(run_id, status="failed", summary=summary, error=f"Command exited {process.returncode}")
            failed_run = store.get_pipeline_run(run_id)
            _record_postgres_run_state(failed_run, status="failed", summary=summary or failed_run.get("summary") or {}, error=failed_run.get("error"))
    except Exception as error:  # noqa: BLE001 - background run errors must be captured for the UI.
        if store is not None:
            store.mark_pipeline_run_finished(run_id, status="failed", error=f"{type(error).__name__}: {error}")
            failed_run = store.get_pipeline_run(run_id)
            _record_postgres_run_state(failed_run, status="failed", summary=failed_run.get("summary") or {}, error=failed_run.get("error"))
    finally:
        with _RUN_PROCESS_LOCK:
            _RUN_PROCESSES.pop(run_id, None)


def _record_postgres_run_state(run: dict[str, Any], *, status: str, summary: dict[str, Any], error: str | None = None) -> None:
    try:
        record_postgres_pipeline_run_state_if_configured(run=run, status=status, summary=summary, error=error)
    except Exception:  # noqa: BLE001 - SQLite run state and filesystem artifacts remain authoritative for the dev runner.
        return


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
