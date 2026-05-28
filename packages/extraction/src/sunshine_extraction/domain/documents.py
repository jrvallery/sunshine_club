"""Source document domain contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".html", ".htm", ".csv", ".json", ".jsonl", ".xml"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".gif", ".bmp", ".webp"}
SPREADSHEET_EXTENSIONS = {".xlsx", ".xlsm"}


@dataclass(frozen=True)
class SampleFile:
    sample_path: Path
    source_path: str
    relative_path: str
    sample_group: str
    sample_number: int | None
    index_row: dict[str, Any]
