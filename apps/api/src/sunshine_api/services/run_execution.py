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

from sunshine_api.review_store import ReviewStore


from sunshine_api.services.run_reports import _read_live_run_summary, _read_run_summary

_RUN_PROCESSES: dict[int, subprocess.Popen[str]] = {}
_RUN_PROCESS_LOCK = threading.Lock()
_RUN_PROGRESS_PATTERN = re.compile(r"\[(?P<current>\d+)/(?P<total>\d+)\]")


def _execute_run(run_id: int, command: list[str], output_dir: str, import_on_success: bool) -> None:
    store = review_store()
    store.mark_pipeline_run_started(run_id)
    try:
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
            return
        if process.returncode == 0:
            if import_on_success and (Path(output_dir) / "sample-pipeline-results.jsonl").exists():
                store.import_langgraph_output(output_dir, sample_routed_per_bucket=0)
            store.mark_pipeline_run_finished(run_id, status="succeeded", summary=summary)
        else:
            store.mark_pipeline_run_finished(run_id, status="failed", summary=summary, error=f"Command exited {process.returncode}")
    except Exception as error:  # noqa: BLE001 - background run errors must be captured for the UI.
        store.mark_pipeline_run_finished(run_id, status="failed", error=f"{type(error).__name__}: {error}")
    finally:
        with _RUN_PROCESS_LOCK:
            _RUN_PROCESSES.pop(run_id, None)


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

