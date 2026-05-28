"""Provider-neutral technical file probe contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class FileProbe:
    source_path: str
    relative_path: str
    sample_path: str
    provider: str
    status: str
    mime_type: str | None
    extension: str
    media_type: str
    size_bytes: int
    page_count: int | None
    embedded_text_chars: int | None
    image_only_pdf_likelihood: float | None
    encrypted: bool | None
    width: int | None
    height: int | None
    warnings: list[str]
    metadata: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        return asdict(self)
