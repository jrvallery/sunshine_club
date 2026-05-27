"""Run the document graph against golden labels and emit quality artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import subprocess
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
    load_taxonomy_options,
    llm_tag_inspector_from_env,
    ocr_executor_from_env,
)
from sunshine_extraction.semantic_index import DEFAULT_INDEX_DB, DEFAULT_LABELS_DB


DEFAULT_EVAL_OUTPUT_DIR = ".local/pipeline-eval"
DEFAULT_ACCEPTANCE_THRESHOLDS = {
    "golden_label_count": 75,
    "primary_taxonomy_coverage": 1.0,
    "high_risk_label_min_count": 2,
    "content_class_accuracy": 0.95,
    "primary_accuracy": 0.88,
    "high_risk_primary_accuracy": 0.80,
    "ocr_quality_accuracy": 0.90,
    "placement_destination_accuracy": 0.90,
    "privacy_accuracy": 1.0,
    "external_model_usage_tracked": 1.0,
    "sensitive_false_accepts": 0,
    "source_file_mutations": 0,
}
HIGH_RISK_PRIMARY_TAGS = {
    "meeting_records",
    "finance_treasurer_records",
    "donations_receipts_fundraising",
    "membership_rosters_yearbooks",
    "dental_program",
    "senior_smiles",
    "scholarships",
    "legal_insurance_compliance",
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
    correct_destination_path: str | None
    correct_placement_year: str | None
    correct_privacy: str | None
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
    run_metadata = _eval_run_metadata(
        labels_db=labels_db,
        output_dir=output_path,
        limit=limit,
        taxonomy_path=taxonomy_path,
        semantic_index_path=semantic_index_path,
        embedding_provider=embedding_provider,
        llm_tag_inspector=llm_tag_inspector,
        ocr_executor=ocr_executor,
    )

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
            embedding_failure_mode="review",
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
        run_metadata=run_metadata,
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
        _optional_column(columns, "correct_destination_path"),
        _optional_column(columns, "correct_placement_year"),
        _optional_column(columns, "correct_privacy"),
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
                correct_destination_path=_optional_row_text(row, "correct_destination_path"),
                correct_placement_year=_optional_row_text(row, "correct_placement_year"),
                correct_privacy=_optional_row_text(row, "correct_privacy"),
                notes=_optional_row_text(row, "notes"),
            )
        )
    return labels


def _evaluation_row(label: GoldenEvalLabel, final_result: dict[str, Any], graph_output_dir: Path) -> dict[str, Any]:
    predicted_primary = final_result.get("top_tag_candidate")
    correct_secondary = set(label.correct_secondary_tags)
    predicted_secondary = set(_string_list(final_result.get("secondary_tags", [])))
    semantic_examples = _semantic_examples(final_result.get("semantic_examples", []))
    semantic_same_family_top5_count = sum(1 for example in semantic_examples[:5] if example.get("correct_primary_tag") == label.correct_primary_tag)
    semantic_top1_primary_tag = semantic_examples[0].get("correct_primary_tag") if semantic_examples else None
    semantic_retrieval_quality = _semantic_retrieval_quality(
        semantic_examples,
        correct_primary_tag=label.correct_primary_tag,
        predicted_primary_tag=predicted_primary,
    )
    route_status = str(final_result.get("route_status") or "unknown")
    review_required = route_status != "route_candidate"
    primary_correct = predicted_primary == label.correct_primary_tag
    content_class_correct = None
    if label.content_class:
        content_class_correct = final_result.get("final_class") == label.content_class
    review_routing_correct = None
    if label.expected_review_required is not None:
        review_routing_correct = review_required == label.expected_review_required
    ocr_fallback_used = _has_warning_prefix(final_result.get("warnings", []), "ocr_fallback_used:")
    llm_status = final_result.get("llm_status")
    llm_structured_output_valid = True if llm_status == "inspected" else False if llm_status in {"invalid", "failed"} else None
    placement_destination_correct = None
    if label.correct_destination_path:
        placement_destination_correct = final_result.get("destination_path") == label.correct_destination_path
    placement_year_correct = None
    if label.correct_placement_year:
        placement_year_correct = str(final_result.get("placement", {}).get("placement_year_label") or "") == label.correct_placement_year
    privacy_correct = None
    if label.correct_privacy:
        privacy_correct = final_result.get("default_privacy") == label.correct_privacy

    failure_reasons = []
    if not primary_correct:
        failure_reasons.append("primary_tag_mismatch")
    if content_class_correct is False:
        failure_reasons.append("content_class_mismatch")
    if review_routing_correct is False:
        failure_reasons.append("review_routing_mismatch")
    if label.ocr_quality_label and final_result.get("quality") != label.ocr_quality_label:
        failure_reasons.append("ocr_quality_mismatch")
    if placement_destination_correct is False:
        failure_reasons.append("placement_destination_mismatch")
    if placement_year_correct is False:
        failure_reasons.append("placement_year_mismatch")
    if privacy_correct is False:
        failure_reasons.append("privacy_mismatch")
    if "embedding_quality_unavailable" in _string_list(final_result.get("warnings", [])):
        failure_reasons.append("embedding_quality_unavailable")
    if not primary_correct and semantic_retrieval_quality in {"missing", "weak", "misleading"}:
        failure_reasons.append(f"semantic_retrieval_{semantic_retrieval_quality}")

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
        "ocr_fallback_used": ocr_fallback_used,
        "expected_destination_path": label.correct_destination_path,
        "predicted_destination_path": final_result.get("destination_path"),
        "placement_destination_correct": placement_destination_correct,
        "expected_placement_year": label.correct_placement_year,
        "predicted_placement_year": final_result.get("placement", {}).get("placement_year_label") if isinstance(final_result.get("placement"), dict) else None,
        "placement_year_correct": placement_year_correct,
        "expected_privacy": label.correct_privacy,
        "predicted_privacy": final_result.get("default_privacy"),
        "privacy_correct": privacy_correct,
        "sensitive_record": label.sensitive_record,
        "route_status": route_status,
        "review_reason": final_result.get("review_reason"),
        "tag_confidence": final_result.get("tag_confidence"),
        "embedding_status": final_result.get("embedding_status"),
        "llm_status": llm_status,
        "llm_structured_output_valid": llm_structured_output_valid,
        "semantic_example_count": len(semantic_examples),
        "semantic_same_family_top5_count": semantic_same_family_top5_count,
        "semantic_top1_primary_tag": semantic_top1_primary_tag,
        "semantic_retrieval_quality": semantic_retrieval_quality,
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
    run_metadata: dict[str, Any],
) -> dict[str, Any]:
    total = len(evaluated)
    model_usage = _model_usage_summary(model_usage_rows)
    primary_tag_metrics = _primary_tag_metrics(evaluated)
    golden_label_readiness = _golden_label_readiness(labels, run_metadata.get("taxonomy_path") or DEFAULT_TAXONOMY_PATH)
    high_risk_metrics = {
        tag: metric
        for tag, metric in primary_tag_metrics.items()
        if tag in HIGH_RISK_PRIMARY_TAGS
    }
    high_risk_min_accuracy = min((metric["accuracy"] for metric in high_risk_metrics.values()), default=None)
    metrics = {
        "primary_accuracy": _safe_divide(totals["primary_correct"], total),
        "content_class_accuracy": _safe_divide(totals["content_class_correct"], totals["content_class_labeled"]),
        "secondary_precision": _safe_divide(totals["secondary_true_positive"], totals["secondary_true_positive"] + totals["secondary_false_positive"]),
        "secondary_recall": _safe_divide(totals["secondary_true_positive"], totals["secondary_true_positive"] + totals["secondary_false_negative"]),
        "ocr_quality_accuracy": _safe_divide(totals["ocr_quality_correct"], totals["ocr_quality_labeled"]),
        "review_routing_accuracy": _safe_divide(totals["review_routing_correct"], totals["review_routing_labeled"]),
        "review_routing_precision": _safe_divide(totals["review_true_positive"], totals["review_true_positive"] + totals["review_false_positive"]),
        "review_routing_recall": _safe_divide(totals["review_true_positive"], totals["review_true_positive"] + totals["review_false_negative"]),
        "review_false_accepts": totals["review_false_negative"],
        "ocr_fallback_rate": _safe_divide(totals["ocr_fallback_used"], total),
        "llm_structured_output_validity_rate": _safe_divide(totals["llm_structured_output_valid"], totals["llm_structured_output_attempted"]),
        "placement_destination_accuracy": _safe_divide(totals["placement_destination_correct"], totals["placement_destination_labeled"]),
        "placement_year_accuracy": _safe_divide(totals["placement_year_correct"], totals["placement_year_labeled"]),
        "privacy_accuracy": _safe_divide(totals["privacy_correct"], totals["privacy_labeled"]),
        "sensitive_false_accepts": totals["sensitive_false_accepts"],
        "embedding_success_rate": _safe_divide(
            model_usage.get("embedding_successful_calls", 0),
            model_usage.get("embedding_attempted_calls", 0),
        ),
        "semantic_same_family_top5_rate": _safe_divide(totals["semantic_same_family_top5"], total),
        "high_risk_primary_accuracy_min": high_risk_min_accuracy,
        "source_file_mutations": 0,
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
        "primary_tag_metrics": primary_tag_metrics,
        "high_risk_primary_tag_metrics": high_risk_metrics,
        "golden_label_readiness": golden_label_readiness,
        "by_route_status": dict(sorted(counters["by_route_status"].items())),
        "by_quality": dict(sorted(counters["by_quality"].items())),
        "by_embedding_status": dict(sorted(counters["by_embedding_status"].items())),
        "by_llm_status": dict(sorted(counters["by_llm_status"].items())),
        "by_failure_reason": dict(sorted(counters["by_failure_reason"].items())),
        "model_usage": model_usage,
        "run_metadata": run_metadata,
        "acceptance_gate": _acceptance_gate(metrics, model_usage, golden_label_readiness),
        "artifacts": {
            "summary": str(output_dir / "eval-summary.json"),
            "results": str(output_dir / "eval-results.jsonl"),
            "confusion_matrix": str(output_dir / "eval-confusion-matrix.json"),
            "failures": str(output_dir / "eval-failures.jsonl"),
            "model_usage": str(output_dir / "eval-model-usage.jsonl"),
        },
    }


def _acceptance_gate(metrics: dict[str, Any], model_usage: dict[str, Any], golden_label_readiness: dict[str, Any]) -> dict[str, Any]:
    high_risk_counts = golden_label_readiness.get("high_risk_label_counts") or {}
    high_risk_min_count = min(high_risk_counts.values(), default=None)
    checks = [
        _minimum_check("golden_label_count", golden_label_readiness.get("total_golden_labels"), DEFAULT_ACCEPTANCE_THRESHOLDS["golden_label_count"]),
        _minimum_check("primary_taxonomy_coverage", golden_label_readiness.get("primary_coverage_rate"), DEFAULT_ACCEPTANCE_THRESHOLDS["primary_taxonomy_coverage"]),
        _minimum_check("high_risk_label_min_count", high_risk_min_count, DEFAULT_ACCEPTANCE_THRESHOLDS["high_risk_label_min_count"]),
        _minimum_check("content_class_accuracy", metrics.get("content_class_accuracy"), DEFAULT_ACCEPTANCE_THRESHOLDS["content_class_accuracy"]),
        _minimum_check("primary_accuracy", metrics.get("primary_accuracy"), DEFAULT_ACCEPTANCE_THRESHOLDS["primary_accuracy"]),
        _minimum_check("high_risk_primary_accuracy", metrics.get("high_risk_primary_accuracy_min"), DEFAULT_ACCEPTANCE_THRESHOLDS["high_risk_primary_accuracy"]),
        _minimum_check("ocr_quality_accuracy", metrics.get("ocr_quality_accuracy"), DEFAULT_ACCEPTANCE_THRESHOLDS["ocr_quality_accuracy"]),
        _minimum_check("placement_destination_accuracy", metrics.get("placement_destination_accuracy"), DEFAULT_ACCEPTANCE_THRESHOLDS["placement_destination_accuracy"]),
        _minimum_check("privacy_accuracy", metrics.get("privacy_accuracy"), DEFAULT_ACCEPTANCE_THRESHOLDS["privacy_accuracy"]),
        _maximum_check("sensitive_false_accepts", metrics.get("sensitive_false_accepts"), DEFAULT_ACCEPTANCE_THRESHOLDS["sensitive_false_accepts"]),
        _maximum_check("source_file_mutations", metrics.get("source_file_mutations"), DEFAULT_ACCEPTANCE_THRESHOLDS["source_file_mutations"]),
        _maximum_check("embedding_placeholder_calls", model_usage.get("embedding_placeholder_calls", 0), 0),
        _maximum_check("embedding_failed_calls", model_usage.get("embedding_failed_calls", 0), 0),
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


def _golden_label_readiness(labels: list[GoldenEvalLabel], taxonomy_path: str | Path) -> dict[str, Any]:
    taxonomy = load_taxonomy_options(taxonomy_path)
    primary_counts = Counter(label.correct_primary_tag for label in labels if label.correct_primary_tag)
    missing_primary_tags = [tag for tag in taxonomy.primary_tags if primary_counts.get(tag, 0) == 0]
    high_risk_label_counts = {
        tag: int(primary_counts.get(tag, 0))
        for tag in sorted(HIGH_RISK_PRIMARY_TAGS)
    }
    underrepresented_high_risk_tags = [
        tag
        for tag, count in high_risk_label_counts.items()
        if count < DEFAULT_ACCEPTANCE_THRESHOLDS["high_risk_label_min_count"]
    ]
    total_primary_tags = len(taxonomy.primary_tags)
    covered_primary_count = total_primary_tags - len(missing_primary_tags)
    label_count_ready = len(labels) >= DEFAULT_ACCEPTANCE_THRESHOLDS["golden_label_count"]
    primary_coverage_ready = not missing_primary_tags
    high_risk_ready = not underrepresented_high_risk_tags
    return {
        "ready": label_count_ready and primary_coverage_ready and high_risk_ready,
        "minimum_label_count": DEFAULT_ACCEPTANCE_THRESHOLDS["golden_label_count"],
        "total_golden_labels": len(labels),
        "label_count_ready": label_count_ready,
        "taxonomy_primary_count": total_primary_tags,
        "covered_primary_count": covered_primary_count,
        "primary_coverage_rate": _safe_divide(covered_primary_count, total_primary_tags),
        "missing_primary_tags": missing_primary_tags,
        "minimum_high_risk_labels_per_category": DEFAULT_ACCEPTANCE_THRESHOLDS["high_risk_label_min_count"],
        "high_risk_label_counts": high_risk_label_counts,
        "underrepresented_high_risk_tags": underrepresented_high_risk_tags,
        "primary_label_counts": dict(sorted(primary_counts.items())),
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
        if row["expected_review_required"] and row["predicted_review_required"]:
            totals["review_true_positive"] += 1
        elif not row["expected_review_required"] and row["predicted_review_required"]:
            totals["review_false_positive"] += 1
        elif row["expected_review_required"] and not row["predicted_review_required"]:
            totals["review_false_negative"] += 1
        elif not row["expected_review_required"] and not row["predicted_review_required"]:
            totals["review_true_negative"] += 1
    if row.get("ocr_fallback_used"):
        totals["ocr_fallback_used"] += 1
    if row.get("llm_structured_output_valid") is not None:
        totals["llm_structured_output_attempted"] += 1
        if row.get("llm_structured_output_valid"):
            totals["llm_structured_output_valid"] += 1
    if row["placement_destination_correct"] is not None:
        totals["placement_destination_labeled"] += 1
        if row["placement_destination_correct"]:
            totals["placement_destination_correct"] += 1
    if row["placement_year_correct"] is not None:
        totals["placement_year_labeled"] += 1
        if row["placement_year_correct"]:
            totals["placement_year_correct"] += 1
    if row["privacy_correct"] is not None:
        totals["privacy_labeled"] += 1
        if row["privacy_correct"]:
            totals["privacy_correct"] += 1
    if row["predicted_review_required"]:
        totals["review_required"] += 1
    else:
        totals["route_candidate"] += 1
    if int(row.get("semantic_same_family_top5_count") or 0) > 0:
        totals["semantic_same_family_top5"] += 1
    if label.sensitive_record and not row["predicted_review_required"] and not row["primary_correct"]:
        totals["sensitive_false_accepts"] += 1


def _primary_tag_metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_tag: dict[str, Counter[str]] = {}
    for row in rows:
        tag = str(row.get("correct_primary_tag") or "unknown")
        by_tag.setdefault(tag, Counter())
        by_tag[tag]["total"] += 1
        if row.get("primary_correct"):
            by_tag[tag]["correct"] += 1
        if row.get("predicted_review_required"):
            by_tag[tag]["review_required"] += 1
    return {
        tag: {
            "total": int(counts["total"]),
            "correct": int(counts["correct"]),
            "accuracy": _safe_divide(counts["correct"], counts["total"]),
            "review_required": int(counts["review_required"]),
            "review_required_rate": _safe_divide(counts["review_required"], counts["total"]),
        }
        for tag, counts in sorted(by_tag.items())
    }


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
    embedding_attempted_calls = 0
    embedding_successful_calls = 0
    embedding_placeholder_calls = 0
    embedding_failed_calls = 0
    embedding_provider_models: Counter[str] = Counter()
    embedding_dimensions: Counter[str] = Counter()
    for row in rows:
        by_provider[str(row.get("provider") or "unknown")] += 1
        by_purpose[str(row.get("purpose") or "unknown")] += 1
        cost_basis = str(row.get("cost_basis") or "unknown")
        by_cost_basis[cost_basis] += 1
        runtime_ms += int(row.get("runtime_ms") or 0)
        if cost_basis == "external" and row.get("estimated_cost_usd") is None:
            unknown_external_cost_calls += 1
        if str(row.get("purpose") or "").endswith("embedding"):
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            raw_call_count = metadata.get("call_count")
            call_count = int(raw_call_count) if raw_call_count is not None else 1
            status = str(row.get("status") or "unknown")
            provider_model = f"{row.get('provider') or 'unknown'}:{row.get('model') or 'unknown'}"
            embedding_provider_models[provider_model] += call_count
            if metadata.get("embedding_dimensions") is not None:
                embedding_dimensions[str(metadata.get("embedding_dimensions"))] += call_count
            embedding_attempted_calls += call_count
            if status == "ok":
                embedding_successful_calls += call_count
            elif status == "placeholder":
                embedding_placeholder_calls += call_count
            elif status == "failed":
                embedding_failed_calls += call_count
    return {
        "total_model_usage_rows": len(rows),
        "by_provider": dict(sorted(by_provider.items())),
        "by_purpose": dict(sorted(by_purpose.items())),
        "by_cost_basis": dict(sorted(by_cost_basis.items())),
        "external_call_count": sum(count for basis, count in by_cost_basis.items() if basis == "external"),
        "unknown_external_cost_calls": unknown_external_cost_calls,
        "embedding_attempted_calls": embedding_attempted_calls,
        "embedding_successful_calls": embedding_successful_calls,
        "embedding_placeholder_calls": embedding_placeholder_calls,
        "embedding_failed_calls": embedding_failed_calls,
        "embedding_provider_models": dict(sorted(embedding_provider_models.items())),
        "embedding_dimensions": dict(sorted(embedding_dimensions.items())),
        "total_runtime_ms": runtime_ms,
        "external_cost": None,
        "external_cost_note": "Cost is unavailable unless provider token/cost metadata is present.",
    }


def _eval_run_metadata(
    *,
    labels_db: str | Path,
    output_dir: Path,
    limit: int | None,
    taxonomy_path: str | Path,
    semantic_index_path: str | Path | None,
    embedding_provider: EmbeddingProvider | None,
    llm_tag_inspector: LLMTagInspector | None,
    ocr_executor: OcrExecutor | None,
) -> dict[str, Any]:
    return {
        "run_kind": "pipeline_eval",
        "labels_db": str(labels_db),
        "output_dir": str(output_dir),
        "limit": limit,
        "taxonomy_path": str(taxonomy_path),
        "taxonomy_version": Path(taxonomy_path).name,
        "semantic_index_path": str(semantic_index_path) if semantic_index_path else None,
        "embedding_provider": _provider_name(embedding_provider),
        "embedding_model": str(getattr(embedding_provider, "model", "")) if embedding_provider is not None else None,
        "embedding_dimensions": getattr(embedding_provider, "dimensions", None),
        "llm_provider": str(getattr(llm_tag_inspector, "provider_name", "")) if llm_tag_inspector is not None else "disabled",
        "llm_model": str(getattr(llm_tag_inspector, "model", "disabled")) if llm_tag_inspector is not None else "disabled",
        "ocr_mode": ocr_executor.__class__.__name__ if ocr_executor is not None else "default",
        "git_commit": _git_commit(),
    }


def _provider_name(provider: Any) -> str | None:
    if provider is None:
        return None
    return str(getattr(provider, "provider_name", "") or provider.__class__.__name__.replace("EmbeddingProvider", "").lower() or "unknown")


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path.cwd(), text=True).strip()
    except Exception:  # noqa: BLE001 - metadata should not break eval runs.
        return None


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
        "expected_destination_path": label.correct_destination_path,
        "predicted_destination_path": None,
        "placement_destination_correct": False if label.correct_destination_path else None,
        "expected_placement_year": label.correct_placement_year,
        "predicted_placement_year": None,
        "placement_year_correct": False if label.correct_placement_year else None,
        "expected_privacy": label.correct_privacy,
        "predicted_privacy": None,
        "privacy_correct": False if label.correct_privacy else None,
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


def _has_warning_prefix(warnings: Any, prefix: str) -> bool:
    return any(warning.startswith(prefix) for warning in _string_list(warnings))


def _semantic_examples(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _semantic_retrieval_quality(
    examples: list[dict[str, Any]],
    *,
    correct_primary_tag: str,
    predicted_primary_tag: Any,
) -> str:
    if not examples:
        return "missing"
    top5 = examples[:5]
    same_family = [example for example in top5 if example.get("correct_primary_tag") == correct_primary_tag]
    if same_family:
        return "supportive"
    predicted_matches = [example for example in top5 if example.get("correct_primary_tag") == predicted_primary_tag]
    if predicted_matches:
        return "misleading"
    return "weak"


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
