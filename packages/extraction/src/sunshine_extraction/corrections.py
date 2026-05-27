"""Apply human review decisions to content-class probe results."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO


ALLOWED_DECISIONS = {
    "accept_after_class",
    "change_to_document",
    "change_to_scanned_document",
    "change_to_image",
    "change_to_spreadsheet",
    "defer_technical",
    "ignore_system_artifact",
}
ALLOWED_CLASSES = {
    "document",
    "scanned_document",
    "image",
    "spreadsheet",
    "shortcut",
    "archive",
    "image_edit_sidecar",
    "video",
    "database",
    "unknown",
}


def apply_review_decisions(
    probe_results_path: str | Path,
    review_index_path: str | Path,
    review_decisions_path: str | Path,
    *,
    overrides_path: str | Path,
    corrected_path: str | Path,
    summary_path: str | Path,
) -> dict[str, Any]:
    probe_results = Path(probe_results_path)
    review_index = _read_review_index(Path(review_index_path))
    decisions = _read_review_decisions(Path(review_decisions_path), review_index)
    overrides = Path(overrides_path)
    corrected = Path(corrected_path)
    summary = Path(summary_path)

    counters: Counter[str] = Counter()
    final_class_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    deferred_counts: Counter[str] = Counter()
    override_rows: list[dict[str, Any]] = []
    corrected_rows = 0

    overrides.parent.mkdir(parents=True, exist_ok=True)
    corrected.parent.mkdir(parents=True, exist_ok=True)
    with probe_results.open("r", encoding="utf-8") as input_file, corrected.open("w", encoding="utf-8") as corrected_file:
        for line in input_file:
            row = json.loads(line)
            corrected_row = _corrected_row(row, decisions)
            _write_jsonl(corrected_file, corrected_row)
            corrected_rows += 1
            final_class_counts[corrected_row["final_class"]] += 1
            counters[corrected_row["final_status"]] += 1
            if corrected_row.get("review_decision"):
                decision_counts[corrected_row["review_decision"]] += 1
                override_rows.append(_override_row(corrected_row))
            if corrected_row["final_status"] == "deferred_technical":
                deferred_counts[corrected_row["final_class"]] += 1

    with overrides.open("w", encoding="utf-8") as overrides_file:
        for row in override_rows:
            _write_jsonl(overrides_file, row)

    summary_data = {
        "generated_at": datetime.now(UTC).isoformat(),
        "probe_results_path": str(probe_results),
        "review_decisions_path": str(review_decisions_path),
        "total_probe_results": corrected_rows,
        "review_decisions": len(decisions),
        "overrides": len(override_rows),
        "by_final_status": dict(sorted(counters.items())),
        "by_final_class": dict(sorted(final_class_counts.items())),
        "by_review_decision": dict(sorted(decision_counts.items())),
        "deferred_technical_by_class": dict(sorted(deferred_counts.items())),
        "unmatched_review_decisions": _unmatched_decisions(decisions, probe_results),
    }
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(summary_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary_data


def _read_review_index(path: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as input_file:
        for line in input_file:
            row = json.loads(line)
            index[row["link_name"]] = row
    return index


def _read_review_decisions(path: Path, review_index: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    decisions: dict[str, dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8") as input_file:
        for row in csv.DictReader(input_file):
            filename = row["filename"].strip()
            decision = row["decision"].strip()
            correct_class = row["correct_class"].strip()
            notes = row["notes"].strip()
            if not decision or not correct_class:
                raise ValueError(f"Review decision is incomplete for {filename}")
            if decision not in ALLOWED_DECISIONS:
                raise ValueError(f"Unsupported decision {decision!r} for {filename}")
            if correct_class not in ALLOWED_CLASSES:
                raise ValueError(f"Unsupported class {correct_class!r} for {filename}")
            index_row = review_index.get(filename)
            source_path = index_row["source_path"] if index_row else None
            if source_path is None:
                source_path = _source_path_from_copied_review_file(path.parent, filename)
            decisions[source_path] = {
                "filename": filename,
                "decision": decision,
                "correct_class": correct_class,
                "notes": notes,
                "index_row": index_row,
            }
    return decisions


def _source_path_from_copied_review_file(review_dir: Path, filename: str) -> str:
    copied_file = review_dir / filename
    if not copied_file.exists():
        raise ValueError(f"Review decision {filename!r} is not in the review index and no copied file exists")
    return str(copied_file)


def _corrected_row(row: dict[str, Any], decisions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    decision = decisions.get(row["source_path"])
    corrected = dict(row)
    corrected["final_class"] = row["after_class"]
    corrected["final_status"] = "accepted"
    corrected["review_decision"] = None
    corrected["review_notes"] = None
    corrected["review_filename"] = None

    if not decision:
        return corrected

    corrected["review_decision"] = decision["decision"]
    corrected["review_notes"] = decision["notes"]
    corrected["review_filename"] = decision["filename"]
    corrected["final_class"] = decision["correct_class"]
    corrected["final_status"] = _final_status(decision["decision"])
    corrected["requires_review"] = False
    corrected["review_reasons"] = []
    corrected["correction_applied"] = True
    return corrected


def _final_status(decision: str) -> str:
    if decision == "defer_technical":
        return "deferred_technical"
    if decision == "ignore_system_artifact":
        return "ignored"
    return "accepted"


def _override_row(corrected_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": corrected_row["source_path"],
        "relative_path": corrected_row["relative_path"],
        "review_filename": corrected_row["review_filename"],
        "before_class": corrected_row["before_class"],
        "probe_after_class": corrected_row["after_class"],
        "final_class": corrected_row["final_class"],
        "final_status": corrected_row["final_status"],
        "review_decision": corrected_row["review_decision"],
        "review_notes": corrected_row["review_notes"],
    }


def _unmatched_decisions(decisions: dict[str, dict[str, Any]], probe_results: Path) -> list[dict[str, Any]]:
    probe_sources = set()
    with probe_results.open("r", encoding="utf-8") as input_file:
        for line in input_file:
            probe_sources.add(json.loads(line)["source_path"])
    unmatched = []
    for source_path, decision in decisions.items():
        if source_path not in probe_sources:
            unmatched.append(
                {
                    "source_path": source_path,
                    "filename": decision["filename"],
                    "decision": decision["decision"],
                    "correct_class": decision["correct_class"],
                }
            )
    return unmatched


def _write_jsonl(output: TextIO, row: dict[str, Any]) -> None:
    output.write(json.dumps(row, sort_keys=True))
    output.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply review decisions to content-class probe results.")
    parser.add_argument("--probe-results", type=Path, required=True)
    parser.add_argument("--review-index", type=Path, required=True)
    parser.add_argument("--review-decisions", type=Path, required=True)
    parser.add_argument("--overrides", type=Path, required=True)
    parser.add_argument("--corrected", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    apply_review_decisions(
        args.probe_results,
        args.review_index,
        args.review_decisions,
        overrides_path=args.overrides,
        corrected_path=args.corrected,
        summary_path=args.summary,
    )


if __name__ == "__main__":
    main()
