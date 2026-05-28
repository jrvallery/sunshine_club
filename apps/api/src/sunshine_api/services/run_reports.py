"""Artifact readers and aggregate metrics for pipeline run reports."""

from __future__ import annotations

from pathlib import Path
import hashlib
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


def _read_live_run_summary(output_dir: str, current_summary: dict[str, Any]) -> dict[str, Any]:
    output_path = Path(output_dir)
    summary = dict(current_summary)
    results_path = output_path / "sample-pipeline-results.jsonl"
    if results_path.exists():
        processed = _count_jsonl_rows(results_path)
        summary["processed_count"] = processed
        summary.setdefault("graph_run_count", processed)
    else:
        processed = _count_live_graph_run_rows(output_path, "sample-pipeline-results.jsonl")
        if processed:
            summary["processed_count"] = processed
            summary.setdefault("graph_run_count", processed)
    review_path = output_path / "sample-review-queue.jsonl"
    if review_path.exists():
        summary["review_required_count"] = _count_jsonl_rows(review_path)
    else:
        review_required = _count_live_graph_run_rows(output_path, "sample-review-queue.jsonl")
        if review_required:
            summary["review_required_count"] = review_required
    audit_path = output_path / "graph-audit-events.jsonl"
    if audit_path.exists():
        summary["audit_event_count"] = _count_jsonl_rows(audit_path)
    else:
        audit_events = _count_live_graph_run_rows(output_path, "graph-audit-events.jsonl")
        if audit_events:
            summary["audit_event_count"] = audit_events
    return summary


def _count_live_graph_run_rows(output_dir: Path, artifact_name: str) -> int:
    return sum(
        _count_jsonl_rows(path)
        for path in _live_graph_run_artifact_paths(output_dir, artifact_name)
    )


def _count_jsonl_rows(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as input_file:
            return sum(1 for line in input_file if line.strip())
    except OSError:
        return 0


def _progress_total(run: dict[str, Any], summary: dict[str, Any]) -> int | None:
    value = summary.get("selected_sample_count") or summary.get("total_count") or summary.get("graph_run_count")
    if isinstance(value, int | float) and value > 0:
        return int(value)
    return None


def _progress_ratio(run: dict[str, Any], summary: dict[str, Any]) -> float | None:
    value = summary.get("progress_ratio")
    if isinstance(value, int | float):
        return max(0.0, min(float(value), 1.0))
    total = _progress_total(run, summary)
    processed = run.get("processed_count") or summary.get("processed_count") or summary.get("graph_run_count")
    if total and isinstance(processed, int | float):
        return max(0.0, min(float(processed) / total, 1.0))
    if run.get("status") == "succeeded":
        return 1.0
    return None


def _read_run_summary(output_dir: str) -> dict[str, Any]:
    path = Path(output_dir) / "sample-pipeline-summary.json"
    if not path.exists():
        graph_result_path = Path(output_dir) / "graph-result.json"
        if not graph_result_path.exists():
            return {}
        try:
            graph_result = json.loads(graph_result_path.read_text(encoding="utf-8"))
            final_result = graph_result.get("final_result", graph_result)
            return {
                "processed_count": 1,
                "route_candidate_count": 1 if final_result.get("route_status") == "route_candidate" else 0,
                "review_required_count": 0 if final_result.get("route_status") == "route_candidate" else 1,
                "failed_count": 1 if str(final_result.get("route_status", "")).startswith("review_failed") else 0,
                "final_result": final_result,
            }
        except Exception:
            return {}
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return {}


def _load_run_results_by_source(output_dir: str) -> dict[str, dict[str, Any]]:
    output_path = Path(output_dir)
    sample_results_path = output_path / "sample-pipeline-results.jsonl"
    if sample_results_path.exists():
        rows = _rows_by_source(_read_jsonl_file(sample_results_path))
        if rows:
            return rows
    graph_result_path = output_path / "graph-result.json"
    if graph_result_path.exists():
        row = json.loads(graph_result_path.read_text(encoding="utf-8"))
        final_result = row.get("final_result", row)
        source_path = str(final_result.get("source_path") or final_result.get("sample_path") or "")
        return {source_path: final_result} if source_path else {}
    live_rows = _rows_by_source(_read_live_graph_run_jsonl(output_path, "sample-pipeline-results.jsonl"))
    if live_rows:
        return live_rows
    return {}


def _rows_by_source(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_source: dict[str, dict[str, Any]] = {}
    for row in rows:
        source_path = str(row.get("source_path") or row.get("sample_path") or "")
        if source_path:
            by_source[source_path] = row
    return by_source


def _read_jsonl_file(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as input_file:
            for line in input_file:
                if limit is not None and len(rows) >= limit:
                    break
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
    except OSError:
        return []
    return rows


def _read_run_jsonl_with_live_fallback(output_dir: Path, artifact_name: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    rows = _read_jsonl_file(output_dir / artifact_name, limit=limit)
    if rows:
        return rows
    return _read_live_graph_run_jsonl(output_dir, artifact_name, limit=limit)


def _read_live_graph_run_jsonl(output_dir: str | Path, artifact_name: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _live_graph_run_artifact_paths(Path(output_dir), artifact_name):
        remaining = None if limit is None else max(0, limit - len(rows))
        if remaining == 0:
            break
        rows.extend(_read_jsonl_file(path, limit=remaining))
    return rows


def _live_graph_run_artifact_paths(output_dir: Path, artifact_name: str) -> list[Path]:
    graph_runs_dir = output_dir / "graph-runs"
    if not graph_runs_dir.exists():
        return []
    try:
        run_dirs = sorted(path for path in graph_runs_dir.iterdir() if path.is_dir())
    except OSError:
        return []
    return [run_dir / artifact_name for run_dir in run_dirs if (run_dir / artifact_name).exists()]


def _run_artifacts(output_dir: Path) -> list[dict[str, Any]]:
    names = [
        "sample-pipeline-summary.json",
        "sample-pipeline-results.jsonl",
        "sample-review-queue.jsonl",
        "sample-source-identity.jsonl",
        "sample-file-probes.jsonl",
        "sample-provider-selections.jsonl",
        "sample-extraction-results.jsonl",
        "sample-extraction-validations.jsonl",
        "sample-extraction-repairs.jsonl",
        "sample-quality-gates.jsonl",
        "sample-provider-attempts.jsonl",
        "sample-ocr-documents.jsonl",
        "sample-ocr-pages.jsonl",
        "sample-structure.jsonl",
        "sample-document-segments.jsonl",
        "sample-chunking-results.jsonl",
        "sample-embedding-results.jsonl",
        "sample-model-usage.jsonl",
        "sample-indexing.jsonl",
        "sample-retrieval-results.jsonl",
        "sample-placement-proposals.jsonl",
        "sample-route-decisions.jsonl",
        "sample-import-results.jsonl",
        "artifact-manifest.json",
        "graph-result.json",
        "graph-audit-events.jsonl",
    ]
    artifacts: list[dict[str, Any]] = []
    for name in names:
        path = output_dir / name
        exists = path.exists()
        stat = path.stat() if exists else None
        row_count = _count_jsonl_rows(path) if exists and path.suffix == ".jsonl" else None
        artifacts.append(
            {
                "name": name,
                "path": str(path),
                "exists": exists,
                "size_bytes": stat.st_size if stat else None,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat() if stat else None,
                "row_count": row_count,
                "sha256": _sha256(path) if exists else None,
            }
        )
    return artifacts


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _training_cycle_metrics(
    run: dict[str, Any],
    review_items: list[dict[str, Any]],
    golden_labels: list[dict[str, Any]],
    comparison: dict[str, Any],
) -> dict[str, Any]:
    review_item_ids = {item.get("id") for item in review_items}
    linked_golden = [label for label in golden_labels if label.get("review_item_id") in review_item_ids]
    resolved = [item for item in review_items if item.get("status") == "resolved"]
    accepted = [item for item in resolved if item.get("decision") == "accept"]
    corrected = [item for item in resolved if item.get("decision") == "change"]
    processed = int(run.get("processed_count") or 0)
    review_required = int(run.get("review_required_count") or len(review_items))
    reviewed_with_decision = len(accepted) + len(corrected)
    primary_evaluated = [label for label in linked_golden if label.get("proposed_tag")]
    primary_correct = sum(1 for label in primary_evaluated if label.get("proposed_tag") == label.get("correct_primary_tag"))
    secondary_true_positive = 0
    secondary_false_positive = 0
    secondary_false_negative = 0
    for label in linked_golden:
        proposed = set(label.get("proposed_secondary_tags") or [])
        correct = set(label.get("correct_secondary_tags") or [])
        secondary_true_positive += len(proposed & correct)
        secondary_false_positive += len(proposed - correct)
        secondary_false_negative += len(correct - proposed)
    ocr_failure_count = sum(1 for item in review_items if _review_item_mentions(item, "ocr"))
    tag_disagreement_count = sum(1 for item in review_items if item.get("review_reason") == "llm_tag_disagreement")
    return {
        "files_processed": processed,
        "review_required_count": review_required,
        "review_item_count": len(review_items),
        "ocr_failure_count": ocr_failure_count,
        "tag_disagreement_count": tag_disagreement_count,
        "open_review_count": sum(1 for item in review_items if item.get("status") == "open"),
        "resolved_review_count": len(resolved),
        "accepted_count": len(accepted),
        "corrected_count": len(corrected),
        "golden_labels_created": len(linked_golden),
        "review_rate": _ratio(review_required, processed),
        "ocr_failure_rate": _ratio(ocr_failure_count, processed),
        "resolution_rate": _ratio(len(resolved), len(review_items)),
        "correction_rate": _ratio(len(corrected), reviewed_with_decision),
        "reviewed_primary_accuracy": _ratio(len(accepted), reviewed_with_decision),
        "golden_primary_accuracy": _ratio(primary_correct, len(primary_evaluated)),
        "golden_primary_correct": primary_correct,
        "golden_primary_evaluated": len(primary_evaluated),
        "secondary_precision": _ratio(secondary_true_positive, secondary_true_positive + secondary_false_positive),
        "secondary_recall": _ratio(secondary_true_positive, secondary_true_positive + secondary_false_negative),
        "run_to_run_changed_count": (comparison.get("summary") or {}).get("changed", 0),
        "run_to_run_added_count": (comparison.get("summary") or {}).get("added", 0),
        "run_to_run_removed_count": (comparison.get("summary") or {}).get("removed", 0),
        "previous_run_id": comparison.get("previous_run_id"),
    }


def _review_item_mentions(item: dict[str, Any], needle: str) -> bool:
    text_parts = [item.get("review_reason"), item.get("route_status")]
    text_parts.extend(item.get("warnings") or [])
    text = " ".join(str(part).lower() for part in text_parts if part)
    return needle.lower() in text


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _result_file_rows(results: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    rows = []
    for result in results[:limit]:
        rows.append(
            {
                "source_path": result.get("source_path"),
                "relative_path": result.get("relative_path"),
                "final_class": result.get("final_class"),
                "quality": result.get("quality"),
                "route_status": result.get("route_status"),
                "top_tag_candidate": result.get("top_tag_candidate"),
                "secondary_tags": result.get("secondary_tags") or [],
                "tag_confidence": result.get("tag_confidence"),
                "placement_status": result.get("placement_status"),
                "warnings": result.get("warnings") or [],
                "extraction_text_snippet": result.get("extraction_text_snippet") or result.get("text_snippet") or result.get("extracted_text_snippet"),
            }
        )
    return rows
