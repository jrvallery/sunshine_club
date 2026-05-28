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


__all__ = ["load_provider_benchmark_samples"]
