"""Artifact manifest generation for graph and batch outputs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sunshine_extraction.domain.artifacts import ArtifactManifest, ArtifactManifestEntry

MANIFEST_NAME = "artifact-manifest.json"


def write_artifact_manifest(
    output_dir: str | Path,
    *,
    expected_names: list[str] | tuple[str, ...] | None = None,
    run_id: str | int | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Write an auditable manifest for the artifacts currently in an output directory."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    manifest = build_artifact_manifest(
        output_path,
        expected_names=expected_names,
        run_id=run_id,
        generated_at=generated_at,
    )
    (output_path / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def build_artifact_manifest(
    output_dir: str | Path,
    *,
    expected_names: list[str] | tuple[str, ...] | None = None,
    run_id: str | int | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Return artifact metadata for all expected and currently present top-level files."""

    output_path = Path(output_dir)
    generated = generated_at or datetime.now(UTC).isoformat()
    names = _artifact_names(output_path, expected_names)
    artifacts = [_artifact_entry(output_path, name) for name in names]
    existing = [artifact for artifact in artifacts if artifact["exists"]]
    return ArtifactManifest(
        schema_version=1,
        generated_at=generated,
        run_id=run_id,
        output_dir=str(output_path),
        artifact_count=len(artifacts),
        existing_artifact_count=len(existing),
        missing_artifact_count=len(artifacts) - len(existing),
        total_size_bytes=sum(int(artifact.get("size_bytes") or 0) for artifact in existing),
        artifacts=artifacts,
    ).as_row()


def _artifact_names(output_dir: Path, expected_names: list[str] | tuple[str, ...] | None) -> list[str]:
    names = set(expected_names or [])
    if output_dir.exists():
        names.update(path.name for path in output_dir.iterdir() if path.is_file())
    names.add(MANIFEST_NAME)
    return sorted(names)


def _artifact_entry(output_dir: Path, name: str) -> dict[str, Any]:
    path = output_dir / name
    exists = path.exists()
    suffix = path.suffix.lower()
    entry = ArtifactManifestEntry(
        name=name,
        path=str(path),
        kind=_artifact_kind(path),
        exists=exists,
        size_bytes=None,
        modified_at=None,
        row_count=None,
        sha256=None,
    ).as_row()
    if not exists:
        return entry

    stat = path.stat()
    entry["size_bytes"] = stat.st_size
    entry["modified_at"] = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
    if suffix == ".jsonl":
        entry["row_count"] = _count_jsonl_rows(path)
    if name == MANIFEST_NAME:
        entry["note"] = "self_referential_manifest"
    else:
        entry["sha256"] = _sha256(path)
    return entry


def _artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return "jsonl"
    if suffix == ".json":
        return "json"
    return suffix.removeprefix(".") or "unknown"


def _count_jsonl_rows(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
