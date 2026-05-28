"""QA sample discovery and lookup helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sunshine_extraction.config import INITIAL_SAMPLE_LIMITS
from sunshine_extraction.domain.documents import SampleFile


def select_sample_files(input_root: Path, limits: dict[str, int] | None = None) -> list[SampleFile]:
    active_limits = limits or INITIAL_SAMPLE_LIMITS
    samples: list[SampleFile] = []
    for group, group_limit in active_limits.items():
        index_path = input_root / group / "index.jsonl"
        if not index_path.exists():
            continue
        for row in read_jsonl(index_path)[:group_limit]:
            samples.append(
                SampleFile(
                    sample_path=input_root / group / row["link_name"],
                    source_path=row["source_path"],
                    relative_path=row["relative_path"],
                    sample_group=group,
                    sample_number=row.get("number"),
                    index_row=row,
                )
            )
    return samples


def load_existing_content_class(sample: SampleFile, rows_by_key: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return lookup_by_sample(sample, rows_by_key, artifact_name="corrected content class")


def load_existing_extraction_plan(sample: SampleFile, rows_by_key: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return lookup_by_sample(sample, rows_by_key, artifact_name="extraction plan")


def rows_by_key(path: str | Path) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(Path(path)):
        indexed[row["source_path"]] = row
        indexed[row["relative_path"]] = row
    return indexed


def lookup_by_sample(sample: SampleFile, rows: dict[str, dict[str, Any]], *, artifact_name: str) -> dict[str, Any]:
    row = rows.get(sample.source_path) or rows.get(sample.relative_path)
    if row is None:
        raise ValueError(f"Missing {artifact_name} row for {sample.relative_path}")
    return row


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as input_file:
        return [json.loads(line) for line in input_file if line.strip()]
