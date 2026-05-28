"""OCR artifact summary helpers."""

from __future__ import annotations

from collections import Counter
from typing import Any


def build_ocr_summary(page_rows: list[dict[str, Any]], document_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_ocr_status: Counter[str] = Counter(str(row.get("ocr_status") or "unknown") for row in document_rows)
    by_quality: Counter[str] = Counter(str(row.get("quality") or "unknown") for row in document_rows)
    by_warning: Counter[str] = Counter()
    for row in [*page_rows, *document_rows]:
        for warning in row.get("warnings", []):
            by_warning[str(warning)] += 1
    page_seconds = [float(row.get("seconds") or 0) for row in page_rows]
    total_pages = len(page_rows)
    failed_pages = len([row for row in page_rows if row.get("ocr_status") == "failed"])
    return {
        "ocr_document_rows": len(document_rows),
        "ocr_page_rows": len(page_rows),
        "by_ocr_status": dict(sorted(by_ocr_status.items())),
        "by_quality": dict(sorted(by_quality.items())),
        "by_warning": dict(sorted(by_warning.items())),
        "total_pages": total_pages,
        "failed_pages": failed_pages,
        "failed_page_rate": round(failed_pages / total_pages, 4) if total_pages else 0,
        "total_ocr_seconds": round(sum(float(row.get("seconds") or 0) for row in document_rows), 4),
        "average_seconds_per_page": round(sum(page_seconds) / total_pages, 4) if total_pages else 0,
    }
