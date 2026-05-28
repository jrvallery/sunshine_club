"""Stable source-file identity contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SourceIdentity:
    file_id: str
    content_sha256: str
    size_bytes: int
    modified_at_ns: int
    extension: str
    source_path: str
    relative_path: str
    sample_path: str

    def as_row(self) -> dict[str, object]:
        return asdict(self)
