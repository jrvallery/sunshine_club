"""Run the document graph against golden labels and emit quality artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sunshine_extraction.embeddings import EmbeddingProvider
from sunshine_extraction.graph.runtime import run_document_graph
from sunshine_extraction.sample_pipeline import (
    DEFAULT_TAXONOMY_PATH,
    LLMTagInspector,
    OcrExecutor,
    load_pipeline_env,
    llm_tag_inspector_from_env,
    ocr_executor_from_env,
)
from sunshine_extraction.semantic_index import DEFAULT_INDEX_DB, DEFAULT_LABELS_DB


DEFAULT_EVAL_OUTPUT_DIR = ".local/pipeline-eval"
DEFAULT_ACCEPTANCE_THRESHOLDS = {
    "content_class_accuracy": 0.95,
    "primary_accuracy": 0.88,
    "ocr_quality_accuracy": 0.90,
    "external_model_usage_tracked": 1.0,
    "sensitive_false_accepts": 0,
}


@dataclass(frozen=True)
class GoldenEvalLabel:
    id: int
    source_path: str
    relative_path: str
    sample_path: str | None
    correct_primary_tag: str
    correct_secondary_tags: list[str]
    content_class: str | None
    ocr_quality_label: str | None
    expected_review_required: bool | None
    sensitive_record: bool
    notes: str | None


def run_golden_pipeline_evaluation(
    labels_db: str | Path = DEFAULT_LABELS_DB,
    *,
    output_dir: str | Path = DEFAULT_EVAL_OUTPUT_DIR,
    limit: int | None = None,
    taxonomy_path: str | Path = DEFAULT_TAXONOMY_PATH,
    embedding_provider: EmbeddingProvider | None = None,
    llm_tag_inspector: LLMTagInspector | None = None,
    ocr_executor: OcrExecutor | None = None,
    semantic_index_path: str | Path | None = DEFAULT_INDEX_DB,
    progress: bool = False,
) -> dict[str, Any]:
    """Evaluate the current graph by running it against reviewed golden labels."""

    labels = load_golden_eval_labels(labels_db, limit=limit)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    graph_runs_dir = output_path / "graph-runs"
    graph_runs_dir.mkdir(parents=True, exist_ok=True)

    evaluated: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    model_usage_rows: list[dict[str, Any]] = []
    confusion: dict[str, dict[str, int]] = {}
    counters: dict[str, Counter[str]] = {
        "by_route_status": Counter(),
        "by_quality": Counter(),
        "by_embedding_status": Counter(),
        "by_llm_status": Counter(),
        "by_failure_reason": Counter(),
    }
    totals = Counter()

    for index, label in enumerate(labels, start=1):
        if progress:
            print(f"[{index}/{len(labels)}] eval {label.relative_path}", flush=True)
        graph_output_dir = graph_runs_dir / f"{index:05d}"
        input_path = _label_input_path(label)
        if input_path is None:
            row = _missing_file_result(label)
            evaluated.append(row)
            failures.append(_failure_row(label, row, "missing_file"))
            for reason in row["failure_reasons"]:
                counters["by_failure_reason"][reason] += 1
            _update_missing_counters(counters)
            _update_totals(totals, row, label)
            _record_confusion(confusion, label.correct_primary_tag, None)
            continue

        graph_result = run_document_graph(
            input_path,
            output_dir=graph_output_dir,
            source_path=label.source_path,
            relative_path=label.relative_path,
            taxonomy_path=taxonomy_path,
            sample_group="golden-eval",
            sample_number=index,
            embedding_provider=embedding_provider,
            llm_tag_inspector=llm_tag_inspector,
            ocr_executor=ocr_executor,
            semantic_index_path=semantic_index_path,
            progress=progress,
        )
        final_result = graph_result.get("final_result", {})
        model_usage_rows.extend(_model_usage_with_label(label, graph_result.get("model_usage", [])))
        row = _evaluation_row(label, final_result, graph_output_dir)
        evaluated.append(row)
        _record_confusion(confusion, label.correct_primary_tag, row.get("predicted_primary_tag"))
        _update_eval_counters(counters, final_result)
        _update_totals(totals, row, label)
        if row["failure_reasons"]:
            for reason in row["failure_reasons"]:
                counters["by_failure_reason"][reason] += 1
            failures.append(_failure_row(label, row, ";".join(row["failure_reasons"])))

    summary = _summary(
        labels_db=labels_db,
        output_dir=output_path,
        labels=labels,
        evaluated=evaluated,
        failures=failures,
        confusion=confusion,
        counters=counters,
        totals=totals,
        model_usage_rows=model_usage_rows,
    )
    _write_eval_artifacts(output_path, summary, evaluated, confusion, failures, model_usage_rows)
    return summary


def load_golden_eval_labels(labels_db: str | Path, *, limit: int | None = None) -> list[GoldenEvalLabel]:
    columns = _table_columns(labels_db, "golden_labels")
    select_columns = [
        "id",
        "source_path",
        "relative_path",
        "sample_path",
        "correct_primary_tag",
        "correct_secondary_tags_json",
        _optional_column(columns, "content_class"),
        _optional_column(columns, "ocr_quality_label"),
        _optional_column(columns, "expected_review_required"),
        _optional_column(columns, "sensitive_record"),
        _optional_column(columns, "notes"),
    ]
    query = f"""
        select {", ".join(select_columns)}
        from golden_labels
        order by updated_at desc, id desc
    """
    params: list[Any] = []
    if limit is not None:
        query += " limit ?"
        params.append(limit)
    with sqlite3.connect(labels_db) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(query, params).fetchall()
    labels = []
    for row in rows:
        labels.append(
            GoldenEvalLabel(
                id=int(row["id"]),
                source_path=str(row["source_path"]),
                relative_path=str(row["relative_path"]),
                sample_path=str(row["sample_path"]) if row["sample_path"] else None,
                correct_primary_tag=str(row["correct_primary_tag"]),
                correct_secondary_tags=_json_list(row["correct_secondary_tags_json"]),
                content_class=_optional_row_text(row, "content_class"),
                ocr_quality_label=_optional_row_text(row, "ocr_quality_label"),
                expected_review_required=_optional_row_bool(row, "expected_review_required"),
                sensitive_record=bool(_optional_row_bool(row, "sensitive_record") or False),
                notes=_optional_row_text(row, "notes"),
            )
        )
    return labels


def _evaluation_row(label: GoldenEvalLabel, final_result: dict[str, Any], graph_output_dir: Path) -> dict[str, Any]:
    predicted_primary = final_result.get("top_tag_candidate")
    correct_secondary = set(label.correct_secondary_tags)
    predicted_secondary = set(_string_list(final_result.get("secondary_tags", [])))
    route_status = str(final_result.get("route_status") or "unknown")
    review_required = route_status != "route_candidate"
    primary_correct = predicted_primary == label.correct_primary_tag
    content_class_correct = None
    if label.content_class:
        content_class_correct = final_result.get("final_class") == label.content_class
    review_routing_correct = None
    if label.expected_review_required is not None:
        review_routing_correct = review_required == label.expected_review_required

    failure_reasons = []
    if not primary_correct:
        failure_reasons.append("primary_tag_mismatch")
    if content_class_correct is False:
        failure_reasons.append("content_class_mismatch")
    if review_routing_correct is False:
        failure_reasons.append("review_routing_mismatch")
    if label.ocr_quality_label and final_result.get("quality") != label.ocr_quality_label:
        failure_reasons.append("ocr_quality_mismatch")

    return {
        "golden_label_id": label.id,
        "source_path": label.source_path,
        "relative_path": label.relative_path,
        "sample_path": label.sample_path,
        "graph_output_dir": str(graph_output_dir),
        "correct_content_class": label.content_class,
        "predicted_content_class": final_result.get("final_class"),
        "content_class_correct": content_class_correct,
        "correct_primary_tag": label.correct_primary_tag,
        "predicted_primary_tag": predicted_primary,
        "primary_correct": primary_correct,
        "correct_secondary_tags": sorted(correct_secondary),
        "predicted_secondary_tags": sorted(predicted_secondary),
        "secondary_true_positive": len(correct_secondary & predicted_secondary),
        "secondary_false_positive": len(predicted_secondary - correct_secondary),
        "secondary_false_negative": len(correct_secondary - predicted_secondary),
        "expected_ocr_quality": label.ocr_quality_label,
        "predicted_ocr_quality": final_result.get("quality"),
        "ocr_quality_correct": (final_result.get("quality") == label.ocr_quality_label) if label.ocr_quality_label else None,
        "expected_review_required": label.expected_review_required,
        "predicted_review_required": review_required,
        "review_routing_correct": review_routing_correct,
        "sensitive_record": label.sensitive_record,
        "route_status": route_status,
        "review_reason": final_result.get("review_reason"),
        "tag_confidence": final_result.get("tag_confidence"),
        "embedding_status": final_result.get("embedding_status"),
        "llm_status": final_result.get("llm_status"),
        "semantic_example_count": final_result.get("semantic_example_count"),
        "warnings": final_result.get("warnings", []),
        "failure_reasons": failure_reasons,
    }


def _summary(
    *,
    labels_db: str | Path,
    output_dir: Path,
    labels: list[GoldenEvalLabel],
    evaluated: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    confusion: dict[str, dict[str, int]],
    counters: dict[str, Counter[str]],
    totals: Counter,
    model_usage_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    total = len(evaluated)
    model_usage = _model_usage_summary(model_usage_rows)
    metrics = {
        "primary_accuracy": _safe_divide(totals["primary_correct"], total),
        "content_class_accuracy": _safe_divide(totals["content_class_correct"], totals["content_class_labeled"]),
        "secondary_precision": _safe_divide(totals["secondary_true_positive"], totals["secondary_true_positive"] + totals["secondary_false_positive"]),
        "secondary_recall": _safe_divide(totals["secondary_true_positive"], totals["secondary_true_positive"] + totals["secondary_false_negative"]),
        "ocr_quality_accuracy": _safe_divide(totals["ocr_quality_correct"], totals["ocr_quality_labeled"]),
        "review_routing_accuracy": _safe_divide(totals["review_routing_correct"], totals["review_routing_labeled"]),
        "sensitive_false_accepts": totals["sensitive_false_accepts"],
    }
    return {
        "labels_db": str(labels_db),
        "output_dir": str(output_dir),
        "total_golden_labels": len(labels),
        "evaluated_predictions": total,
        "missing_files": counters["by_failure_reason"].get("missing_file", 0),
        "failure_count": len(failures),
        **metrics,
        "review_required_count": totals["review_required"],
        "route_candidate_count": totals["route_candidate"],
        "confusion": confusion,
        "by_route_status": dict(sorted(counters["by_route_status"].items())),
        "by_quality": dict(sorted(counters["by_quality"].items())),
        "by_embedding_status": dict(sorted(counters["by_embedding_status"].items())),
        "by_llm_status": dict(sorted(counters["by_llm_status"].items())),
        "by_failure_reason": dict(sorted(counters["by_failure_reason"].items())),
        "model_usage": model_usage,
        "acceptance_gate": _acceptance_gate(metrics, model_usage),
        "artifacts": {
            "summary": str(output_dir / "eval-summary.json"),
            "results": str(output_dir / "eval-results.jsonl"),
            "confusion_matrix": str(output_dir / "eval-confusion-matrix.json"),
            "failures": str(output_dir / "eval-failures.jsonl"),
            "model_usage": str(output_dir / "eval-model-usage.jsonl"),
        },
    }


def _acceptance_gate(metrics: dict[str, Any], model_usage: dict[str, Any]) -> dict[str, Any]:
    checks = [
        _minimum_check("content_class_accuracy", metrics.get("content_class_accuracy"), DEFAULT_ACCEPTANCE_THRESHOLDS["content_class_accuracy"]),
        _minimum_check("primary_accuracy", metrics.get("primary_accuracy"), DEFAULT_ACCEPTANCE_THRESHOLDS["primary_accuracy"]),
        _minimum_check("ocr_quality_accuracy", metrics.get("ocr_quality_accuracy"), DEFAULT_ACCEPTANCE_THRESHOLDS["ocr_quality_accuracy"]),
        _maximum_check("sensitive_false_accepts", metrics.get("sensitive_false_accepts"), DEFAULT_ACCEPTANCE_THRESHOLDS["sensitive_false_accepts"]),
        _minimum_check(
            "external_model_usage_tracked",
            1.0 if model_usage.get("unknown_external_cost_calls", 0) == 0 else 0.0,
            DEFAULT_ACCEPTANCE_THRESHOLDS["external_model_usage_tracked"],
        ),
    ]
    blocking = [check for check in checks if check["status"] != "pass"]
    return {
        "status": "pass" if not blocking else "fail",
        "thresholds": DEFAULT_ACCEPTANCE_THRESHOLDS,
        "checks": checks,
        "blocking_checks": blocking,
    }


def _minimum_check(name: str, value: Any, threshold: float) -> dict[str, Any]:
    if value is None:
        status = "not_evaluated"
    else:
        status = "pass" if float(value) >= threshold else "fail"
    return {"name": name, "operator": ">=", "value": value, "threshold": threshold, "status": status}


def _maximum_check(name: str, value: Any, threshold: float) -> dict[str, Any]:
    if value is None:
        status = "not_evaluated"
    else:
        status = "pass" if float(value) <= threshold else "fail"
    return {"name": name, "operator": "<=", "value": value, "threshold": threshold, "status": status}


def _update_totals(totals: Counter, row: dict[str, Any], label: GoldenEvalLabel) -> None:
    if row["primary_correct"]:
        totals["primary_correct"] += 1
    totals["secondary_true_positive"] += int(row["secondary_true_positive"])
    totals["secondary_false_positive"] += int(row["secondary_false_positive"])
    totals["secondary_false_negative"] += int(row["secondary_false_negative"])
    if row["content_class_correct"] is not None:
        totals["content_class_labeled"] += 1
        if row["content_class_correct"]:
            totals["content_class_correct"] += 1
    if row["ocr_quality_correct"] is not None:
        totals["ocr_quality_labeled"] += 1
        if row["ocr_quality_correct"]:
            totals["ocr_quality_correct"] += 1
    if row["review_routing_correct"] is not None:
        totals["review_routing_labeled"] += 1
        if row["review_routing_correct"]:
            totals["review_routing_correct"] += 1
    if row["predicted_review_required"]:
        totals["review_required"] += 1
    else:
        totals["route_candidate"] += 1
    if label.sensitive_record and not row["predicted_review_required"] and not row["primary_correct"]:
        totals["sensitive_false_accepts"] += 1


def _update_eval_counters(counters: dict[str, Counter[str]], final_result: dict[str, Any]) -> None:
    counters["by_route_status"][str(final_result.get("route_status") or "unknown")] += 1
    counters["by_quality"][str(final_result.get("quality") or "unknown")] += 1
    counters["by_embedding_status"][str(final_result.get("embedding_status") or "unknown")] += 1
    counters["by_llm_status"][str(final_result.get("llm_status") or "unknown")] += 1


def _update_missing_counters(counters: dict[str, Counter[str]]) -> None:
    counters["by_route_status"]["review_failed_extraction"] += 1
    counters["by_quality"]["missing"] += 1
    counters["by_embedding_status"]["none"] += 1
    counters["by_llm_status"]["none"] += 1


def _model_usage_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_provider: Counter[str] = Counter()
    by_purpose: Counter[str] = Counter()
    by_cost_basis: Counter[str] = Counter()
    runtime_ms = 0
    unknown_external_cost_calls = 0
    for row in rows:
        by_provider[str(row.get("provider") or "unknown")] += 1
        by_purpose[str(row.get("purpose") or "unknown")] += 1
        cost_basis = str(row.get("cost_basis") or "unknown")
        by_cost_basis[cost_basis] += 1
        runtime_ms += int(row.get("runtime_ms") or 0)
        if cost_basis == "external" and row.get("estimated_cost_usd") is None:
            unknown_external_cost_calls += 1
    return {
        "total_model_usage_rows": len(rows),
        "by_provider": dict(sorted(by_provider.items())),
        "by_purpose": dict(sorted(by_purpose.items())),
        "by_cost_basis": dict(sorted(by_cost_basis.items())),
        "external_call_count": sum(count for basis, count in by_cost_basis.items() if basis == "external"),
        "unknown_external_cost_calls": unknown_external_cost_calls,
        "total_runtime_ms": runtime_ms,
        "external_cost": None,
        "external_cost_note": "Cost is unavailable unless provider token/cost metadata is present.",
    }


def _write_eval_artifacts(
    output_dir: Path,
    summary: dict[str, Any],
    evaluated: list[dict[str, Any]],
    confusion: dict[str, dict[str, int]],
    failures: list[dict[str, Any]],
    model_usage_rows: list[dict[str, Any]],
) -> None:
    (output_dir / "eval-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "eval-confusion-matrix.json").write_text(json.dumps(confusion, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_jsonl(output_dir / "eval-results.jsonl", evaluated)
    _write_jsonl(output_dir / "eval-failures.jsonl", failures)
    _write_jsonl(output_dir / "eval-model-usage.jsonl", model_usage_rows)
    with (output_dir / "eval-confusion-matrix.csv").open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=["correct_primary_tag", "predicted_primary_tag", "count"])
        writer.writeheader()
        for actual, predicted_counts in sorted(confusion.items()):
            for predicted, count in sorted(predicted_counts.items()):
                writer.writerow({"correct_primary_tag": actual, "predicted_primary_tag": predicted, "count": count})


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as output_file:
        for row in rows:
            output_file.write(json.dumps(row, sort_keys=True) + "\n")


def _label_input_path(label: GoldenEvalLabel) -> Path | None:
    for candidate in [label.sample_path, label.source_path]:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists() and path.is_file():
            return path
    return None


def _missing_file_result(label: GoldenEvalLabel) -> dict[str, Any]:
    return {
        "golden_label_id": label.id,
        "source_path": label.source_path,
        "relative_path": label.relative_path,
        "sample_path": label.sample_path,
        "graph_output_dir": None,
        "correct_content_class": label.content_class,
        "predicted_content_class": None,
        "content_class_correct": False if label.content_class else None,
        "correct_primary_tag": label.correct_primary_tag,
        "predicted_primary_tag": None,
        "primary_correct": False,
        "correct_secondary_tags": label.correct_secondary_tags,
        "predicted_secondary_tags": [],
        "secondary_true_positive": 0,
        "secondary_false_positive": 0,
        "secondary_false_negative": len(label.correct_secondary_tags),
        "expected_ocr_quality": label.ocr_quality_label,
        "predicted_ocr_quality": None,
        "ocr_quality_correct": False if label.ocr_quality_label else None,
        "expected_review_required": label.expected_review_required,
        "predicted_review_required": True,
        "review_routing_correct": (label.expected_review_required is True) if label.expected_review_required is not None else None,
        "sensitive_record": label.sensitive_record,
        "route_status": "review_failed_extraction",
        "review_reason": "file_missing",
        "tag_confidence": None,
        "embedding_status": None,
        "llm_status": None,
        "semantic_example_count": 0,
        "warnings": ["file_missing"],
        "failure_reasons": ["missing_file", "primary_tag_mismatch"],
    }


def _failure_row(label: GoldenEvalLabel, row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "golden_label_id": label.id,
        "source_path": label.source_path,
        "relative_path": label.relative_path,
        "reason": reason,
        "correct_primary_tag": label.correct_primary_tag,
        "predicted_primary_tag": row.get("predicted_primary_tag"),
        "route_status": row.get("route_status"),
        "review_reason": row.get("review_reason"),
        "warnings": row.get("warnings", []),
    }


def _model_usage_with_label(label: GoldenEvalLabel, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for row in rows:
        enriched.append(
            {
                "golden_label_id": label.id,
                "source_path": label.source_path,
                "relative_path": label.relative_path,
                **row,
            }
        )
    return enriched


def _record_confusion(confusion: dict[str, dict[str, int]], actual: str, predicted: Any) -> None:
    predicted_key = str(predicted or "none")
    confusion.setdefault(actual, {})
    confusion[actual][predicted_key] = confusion[actual].get(predicted_key, 0) + 1


def _table_columns(db_path: str | Path, table_name: str) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(f"pragma table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _optional_column(columns: set[str], name: str) -> str:
    return name if name in columns else f"null as {name}"


def _optional_row_text(row: sqlite3.Row, key: str) -> str | None:
    value = row[key]
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_row_bool(row: sqlite3.Row, key: str) -> bool | None:
    value = row[key]
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return _string_list(parsed)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _safe_divide(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Sunshine graph against golden labels and emit eval artifacts.")
    parser.add_argument("--labels", "--labels-db", dest="labels_db", default=DEFAULT_LABELS_DB)
    parser.add_argument("--output-dir", default=DEFAULT_EVAL_OUTPUT_DIR)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--taxonomy-path", default=DEFAULT_TAXONOMY_PATH)
    parser.add_argument("--semantic-index-path", default=DEFAULT_INDEX_DB)
    parser.add_argument("--disable-semantic-index", action="store_true")
    parser.add_argument("--enable-llm-tags", action="store_true")
    parser.add_argument("--enable-ocr", action="store_true")
    parser.add_argument("--progress", action="store_true")
    return parser.parse_args()


def main() -> None:
    load_pipeline_env()
    args = _parse_args()
    summary = run_golden_pipeline_evaluation(
        args.labels_db,
        output_dir=args.output_dir,
        limit=args.limit,
        taxonomy_path=args.taxonomy_path,
        llm_tag_inspector=llm_tag_inspector_from_env() if args.enable_llm_tags else LLMTagInspector(),
        ocr_executor=ocr_executor_from_env() if args.enable_ocr else None,
        semantic_index_path=None if args.disable_semantic_index else args.semantic_index_path,
        progress=args.progress,
    )
    print(json.dumps({"ok": True, **summary}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
