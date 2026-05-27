"""Evaluate pipeline tag predictions against reviewed golden labels."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from sunshine_extraction.semantic_index import DEFAULT_LABELS_DB


def evaluate_review_db(
    labels_db: str | Path = DEFAULT_LABELS_DB,
    *,
    output: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    with sqlite3.connect(labels_db) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            select
                golden_labels.source_path,
                golden_labels.relative_path,
                golden_labels.correct_primary_tag,
                golden_labels.correct_secondary_tags_json,
                golden_labels.proposed_tag,
                golden_labels.proposed_secondary_tags_json,
                golden_labels.proposed_confidence,
                pipeline_results.top_tag_candidate as latest_primary_tag,
                pipeline_results.secondary_tags_json as latest_secondary_tags_json,
                pipeline_results.tag_confidence as latest_confidence,
                pipeline_results.route_status as latest_route_status
            from golden_labels
            left join pipeline_results on pipeline_results.source_path = golden_labels.source_path
            order by golden_labels.updated_at desc, golden_labels.id desc
            """
        ).fetchall()

    evaluated = []
    missing_latest = 0
    correct_primary = 0
    secondary_true_positive = 0
    secondary_false_positive = 0
    secondary_false_negative = 0
    auto_accept_total = 0
    auto_accept_correct = 0
    confusion: dict[str, dict[str, int]] = {}
    review_required: list[dict[str, Any]] = []
    for row in rows:
        predicted = row["latest_primary_tag"] or row["proposed_tag"]
        if not row["latest_primary_tag"]:
            missing_latest += 1
        is_correct = predicted == row["correct_primary_tag"]
        if is_correct:
            correct_primary += 1
        correct_secondary = set(_json_list(row["correct_secondary_tags_json"]))
        predicted_secondary = set(_json_list(row["latest_secondary_tags_json"] or row["proposed_secondary_tags_json"]))
        secondary_true_positive += len(correct_secondary & predicted_secondary)
        secondary_false_positive += len(predicted_secondary - correct_secondary)
        secondary_false_negative += len(correct_secondary - predicted_secondary)
        if row["latest_route_status"] == "route_candidate":
            auto_accept_total += 1
            if is_correct:
                auto_accept_correct += 1
        if row["latest_route_status"] and row["latest_route_status"] != "route_candidate":
            review_required.append(
                {
                    "source_path": row["source_path"],
                    "relative_path": row["relative_path"],
                    "route_status": row["latest_route_status"],
                    "correct_primary_tag": row["correct_primary_tag"],
                    "predicted_primary_tag": predicted,
                    "predicted_confidence": row["latest_confidence"],
                }
            )
        actual = str(row["correct_primary_tag"])
        predicted_key = str(predicted or "none")
        confusion.setdefault(actual, {})
        confusion[actual][predicted_key] = confusion[actual].get(predicted_key, 0) + 1
        evaluated.append(
            {
                "source_path": row["source_path"],
                "relative_path": row["relative_path"],
                "correct_primary_tag": row["correct_primary_tag"],
                "correct_secondary_tags": sorted(correct_secondary),
                "predicted_primary_tag": predicted,
                "predicted_secondary_tags": sorted(predicted_secondary),
                "predicted_confidence": row["latest_confidence"] if row["latest_confidence"] is not None else row["proposed_confidence"],
                "latest_route_status": row["latest_route_status"],
                "primary_correct": is_correct,
            }
        )

    total = len(evaluated)
    secondary_precision = _safe_divide(secondary_true_positive, secondary_true_positive + secondary_false_positive)
    secondary_recall = _safe_divide(secondary_true_positive, secondary_true_positive + secondary_false_negative)
    report = {
        "labels_db": str(labels_db),
        "total_golden_labels": total,
        "evaluated_predictions": total,
        "missing_latest_pipeline_result": missing_latest,
        "primary_accuracy": (correct_primary / total) if total else None,
        "secondary_precision": secondary_precision,
        "secondary_recall": secondary_recall,
        "review_rate": _safe_divide(len(review_required), total),
        "auto_accept_precision": _safe_divide(auto_accept_correct, auto_accept_total),
        "correct_primary": correct_primary,
        "incorrect_primary": total - correct_primary,
        "secondary_true_positive": secondary_true_positive,
        "secondary_false_positive": secondary_false_positive,
        "secondary_false_negative": secondary_false_negative,
        "auto_accept_total": auto_accept_total,
        "auto_accept_correct": auto_accept_correct,
        "manual_review_required": len(review_required),
        "confusion": confusion,
        "mismatches": [row for row in evaluated if not row["primary_correct"]],
        "files_requiring_manual_review": review_required,
    }
    if output_dir is not None:
        _write_eval_artifacts(Path(output_dir), report, evaluated, confusion, review_required)
    if output is not None:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _safe_divide(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _write_eval_artifacts(
    output_dir: Path,
    report: dict[str, Any],
    evaluated: list[dict[str, Any]],
    confusion: dict[str, dict[str, int]],
    review_required: list[dict[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "semantic-eval-summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with (output_dir / "semantic-eval-results.jsonl").open("w", encoding="utf-8") as output_file:
        for row in evaluated:
            output_file.write(json.dumps(row, sort_keys=True) + "\n")
    with (output_dir / "semantic-confusion-matrix.csv").open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=["correct_primary_tag", "predicted_primary_tag", "count"])
        writer.writeheader()
        for actual, predicted_counts in sorted(confusion.items()):
            for predicted, count in sorted(predicted_counts.items()):
                writer.writerow({"correct_primary_tag": actual, "predicted_primary_tag": predicted, "count": count})
    with (output_dir / "semantic-review-required.csv").open("w", encoding="utf-8", newline="") as output_file:
        fieldnames = ["source_path", "relative_path", "route_status", "correct_primary_tag", "predicted_primary_tag", "predicted_confidence"]
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in review_required:
            writer.writerow(row)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Sunshine semantic tags against golden labels.")
    parser.add_argument("--input-root", help="Accepted for CLI compatibility; evaluation reads the review DB.")
    parser.add_argument("--labels", "--labels-db", dest="labels_db", default=DEFAULT_LABELS_DB)
    parser.add_argument("--output", default=None)
    parser.add_argument("--output-dir", default=".local/semantic-eval")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = evaluate_review_db(args.labels_db, output=args.output, output_dir=args.output_dir)
    print(json.dumps({"ok": True, "output_dir": args.output_dir, **report}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
