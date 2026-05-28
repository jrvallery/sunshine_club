"""Artifact manifest contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ArtifactManifestEntry:
    name: str
    path: str
    kind: str
    exists: bool
    size_bytes: int | None
    modified_at: str | None
    row_count: int | None
    sha256: str | None
    note: str | None = None

    def as_row(self) -> dict[str, Any]:
        row = asdict(self)
        if self.note is None:
            row.pop("note")
        return row


@dataclass(frozen=True)
class ArtifactManifest:
    schema_version: int
    generated_at: str
    run_id: str | int | None
    output_dir: str
    artifact_count: int
    existing_artifact_count: int
    missing_artifact_count: int
    total_size_bytes: int
    artifacts: list[dict[str, Any]]

    def as_row(self) -> dict[str, Any]:
        return asdict(self)
