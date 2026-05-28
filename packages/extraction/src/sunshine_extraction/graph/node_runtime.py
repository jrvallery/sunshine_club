"""Execution wrapper and audit-event helpers for LangGraph nodes."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from sunshine_extraction.graph.state import DocumentPipelineState


def _run_node(name: str, state: DocumentPipelineState, func: Any) -> DocumentPipelineState:
    started = time.monotonic()
    before_warning_count = len(state.get("warnings", []))
    before_error_count = len(state.get("errors", []))
    max_attempts = max(1, int(state.get("retry_attempts", 1)))
    delay_seconds = max(0.0, float(state.get("retry_delay_seconds", 0)))
    attempts = 0
    last_error: Exception | None = None
    while attempts < max_attempts:
        attempts += 1
        try:
            updates = func(state)
            status = "ok"
            summary = _node_summary(name, updates)
            last_error = None
            break
        except Exception as error:  # noqa: BLE001 - graph failures need durable state.
            last_error = error
            if attempts < max_attempts and delay_seconds:
                time.sleep(delay_seconds)
    else:
        assert last_error is not None
        updates = {
            "errors": [
                *state.get("errors", []),
                {"node": name, "error_type": type(last_error).__name__, "message": str(last_error), "attempts": attempts},
            ]
        }
        status = "failed"
        summary = f"{type(last_error).__name__}: {last_error}"
    merged = _merge_state(state, updates)
    event = {
        "node": name,
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "run_id": state.get("run_id"),
        "source_path": state.get("source_path"),
        "relative_path": state.get("relative_path"),
        "duration_ms": round((time.monotonic() - started) * 1000, 2),
        "attempts": attempts,
        "warnings": merged.get("warnings", [])[before_warning_count:],
        "errors": merged.get("errors", [])[before_error_count:],
        "summary": summary,
    }
    merged["audit_events"] = [*state.get("audit_events", []), event]
    return merged

def _merge_state(state: DocumentPipelineState, updates: dict[str, Any]) -> DocumentPipelineState:
    merged: DocumentPipelineState = dict(state)
    for key, value in updates.items():
        if key in {"warnings", "errors"}:
            merged[key] = value
        else:
            merged[key] = value
    return merged

def _node_summary(name: str, updates: dict[str, Any]) -> str:
    if name == "load_file_context" and updates.get("sample"):
        return f"loaded {updates['sample'].relative_path}"
    if name == "classify_content_type" and updates.get("content_class"):
        return f"classified {updates['content_class'].get('final_class')}"
    if name == "probe_file" and updates.get("file_probe"):
        return f"probed {updates['file_probe'].get('media_type')}"
    if name == "plan_extraction" and updates.get("extraction_plan"):
        return f"planned {updates['extraction_plan'].get('strategy')}"
    if name == "extract_content" and updates.get("extraction_result"):
        return f"extracted {updates['extraction_result'].extraction_status}"
    if name == "validate_text_extraction" and updates.get("extraction_result"):
        return f"validated {updates['extraction_result'].plan.get('strategy')}"
    if name == "quality_gate" and updates.get("extraction_quality"):
        return f"quality {updates['extraction_quality'].get('quality')}"
    if name == "chunk_content":
        return f"chunks {len(updates.get('chunks', []))}"
    if name == "embed_chunks":
        return f"embeddings {len(updates.get('embeddings', []))}"
    if name == "retrieve_labeled_examples":
        return f"semantic examples {len(updates.get('semantic_examples', []))}"
    if name == "assign_deterministic_tags":
        return f"deterministic candidates {len(updates.get('deterministic_tag_candidates', []))}"
    if name == "inspect_tags_with_llm" and updates.get("llm_tag_inspection"):
        return f"llm {updates['llm_tag_inspection'].get('llm_status')}"
    if name == "combine_tag_evidence":
        return f"tag candidates {len(updates.get('tag_candidates', []))}"
    if name == "calibrate_tag_confidence" and updates.get("confidence_calibration"):
        return f"calibrated {updates['confidence_calibration'].get('calibrated_confidence')}"
    if name == "resolve_route_or_review" and updates.get("route"):
        return f"route {updates['route'].get('route_status')}"
    if name == "persist_outputs":
        return "persisted graph outputs"
    return "completed"
