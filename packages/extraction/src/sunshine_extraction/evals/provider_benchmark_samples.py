"""Canonical provider benchmark sample manifest loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_provider_benchmark_samples(manifest_path: str | Path, *, sample_root: str | Path | None = None) -> list[dict[str, Any]]:
    """Load benchmark samples from a JSON manifest.

    The manifest format is intentionally small and local-only:

    {
      "samples": [
        {"path": "relative/or/absolute/file.pdf", "category": "scanned_pdf"}
      ]
    }
    """

    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_samples = payload.get("samples") if isinstance(payload, dict) else payload
    if not isinstance(raw_samples, list):
        raise ValueError("Provider benchmark manifest must contain a samples list")
    base = Path(sample_root) if sample_root else path.parent
    samples: list[dict[str, Any]] = []
    for index, raw_sample in enumerate(raw_samples, start=1):
        if not isinstance(raw_sample, dict):
            raise ValueError(f"Provider benchmark manifest sample #{index} must be an object")
        raw_path = str(raw_sample.get("path") or "").strip()
        if not raw_path:
            raise ValueError(f"Provider benchmark manifest sample #{index} is missing path")
        sample_path = Path(raw_path)
        if not sample_path.is_absolute():
            sample_path = base / sample_path
        samples.append(
            {
                "path": sample_path,
                "category": str(raw_sample.get("category") or "uncategorized"),
                "label": str(raw_sample.get("label") or sample_path.name),
                "metadata": raw_sample.get("metadata") if isinstance(raw_sample.get("metadata"), dict) else {},
            }
        )
    return samples


CANONICAL_CATEGORIES = [
    "born_digital_text",
    "image_scan",
    "scanned_pdf",
    "scrapbook_packet",
    "newspaper_packet",
    "financial_table",
]


def generate_provider_benchmark_manifest(
    qa_root: str | Path,
    output_path: str | Path,
    *,
    per_category: int = 2,
) -> dict[str, Any]:
    """Generate a private local benchmark manifest from QA sample indexes."""

    root = Path(qa_root)
    rows = _qa_index_rows(root)
    selected: list[dict[str, Any]] = []
    for category in CANONICAL_CATEGORIES:
        candidates = sorted(
            [row for row in rows if category in _categories_for_row(row)],
            key=lambda row: _candidate_sort_key(row, category),
        )
        for row in candidates[: max(1, int(per_category))]:
            selected.append(_manifest_sample(row, category))

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "description": "Local-only Sunshine provider benchmark manifest generated from QA sample indexes. Do not commit customer paths.",
        "source_qa_root": str(root),
        "categories": CANONICAL_CATEGORIES,
        "samples": selected,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "output_path": str(output),
        "source_qa_root": str(root),
        "sample_count": len(selected),
        "categories": _count(selected, "category"),
        "missing_categories": [category for category in CANONICAL_CATEGORIES if not any(sample["category"] == category for sample in selected)],
        "samples": selected,
    }


def _qa_index_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index_path in sorted(root.glob("*/index.jsonl")):
        group = index_path.parent.name
        with index_path.open("r", encoding="utf-8") as input_file:
            for line_number, line in enumerate(input_file, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    continue
                sample_path = index_path.parent / str(row.get("link_name") or "")
                source_path = Path(str(row.get("source_path") or sample_path))
                row["_group"] = group
                row["_index_path"] = str(index_path)
                row["_line_number"] = line_number
                row["_candidate_path"] = str(source_path if source_path.exists() else sample_path)
                rows.append(row)
    return rows


def _categories_for_row(row: dict[str, Any]) -> set[str]:
    text = _row_text(row)
    suffix = Path(str(row.get("_candidate_path") or "")).suffix.lower()
    after_class = str(row.get("after_class") or "").lower()
    transition = str(row.get("transition_reason") or "").lower()
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    categories: set[str] = set()
    if suffix == ".pdf" and (after_class == "document" or "extractable_text" in transition or int(metadata.get("sample_text_chars") or 0) > 0):
        categories.add("born_digital_text")
    if suffix in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"} and after_class in {"image", "scanned_document"}:
        categories.add("image_scan")
    if suffix == ".pdf" and (after_class == "scanned_document" or "image_only" in transition or int(metadata.get("sample_text_chars") or 0) == 0):
        categories.add("scanned_pdf")
    if "scrapbook" in text or "clipping" in text:
        categories.add("scrapbook_packet")
    if any(term in text for term in ("newspaper", "ledger", "times-call", "times call", "article", "clipping", "spangler", "charlie gunning", "smallgreen")):
        categories.add("newspaper_packet")
    if any(term in text for term in ("treasurer", "budget", "financial", "paypal", "transaction report", "balance", "expense")):
        categories.add("financial_table")
    return categories


def _candidate_sort_key(row: dict[str, Any], category: str) -> tuple[int, int, str]:
    path = Path(str(row.get("_candidate_path") or ""))
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    page_count = int(metadata.get("page_count") or 0)
    suffix = path.suffix.lower()
    pdf_penalty = 0 if suffix == ".pdf" else 1
    if category in {"image_scan", "newspaper_packet"} and suffix in {".jpg", ".jpeg", ".png"}:
        pdf_penalty = 0
    long_doc_bonus = -page_count if category in {"scrapbook_packet", "scanned_pdf", "financial_table"} else 0
    return (pdf_penalty, long_doc_bonus, str(row.get("relative_path") or path))


def _manifest_sample(row: dict[str, Any], category: str) -> dict[str, Any]:
    path = str(row.get("_candidate_path") or row.get("source_path"))
    label = str(row.get("link_name") or Path(path).name)
    return {
        "category": category,
        "label": label,
        "path": path,
        "metadata": {
            "relative_path": row.get("relative_path"),
            "source_path": row.get("source_path"),
            "qa_group": row.get("_group"),
            "index_path": row.get("_index_path"),
            "index_line_number": row.get("_line_number"),
            "after_class": row.get("after_class"),
            "before_class": row.get("before_class"),
            "transition_reason": row.get("transition_reason"),
        },
    }


def _row_text(row: dict[str, Any]) -> str:
    values = [
        row.get("relative_path"),
        row.get("source_path"),
        row.get("link_name"),
        row.get("after_class"),
        row.get("before_class"),
        row.get("transition_reason"),
        row.get("_group"),
    ]
    return " ".join(str(value or "") for value in values).lower()


def _count(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


__all__ = ["CANONICAL_CATEGORIES", "generate_provider_benchmark_manifest", "load_provider_benchmark_samples"]
