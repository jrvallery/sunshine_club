"""Source-file identity helpers for idempotent pipeline runs."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from sunshine_extraction.domain.identity import SourceIdentity
from sunshine_extraction.services.content import SampleFile


def identify_source_file(sample: SampleFile) -> dict[str, object]:
    path = sample.sample_path
    stat = path.stat()
    content_sha256 = _sha256(path)
    identity = SourceIdentity(
        file_id=_file_id(sample.source_path, content_sha256),
        content_sha256=content_sha256,
        size_bytes=stat.st_size,
        modified_at_ns=stat.st_mtime_ns,
        extension=path.suffix.lower(),
        source_path=sample.source_path,
        relative_path=sample.relative_path,
        sample_path=str(path),
    )
    return identity.as_row()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_id(source_path: str, content_sha256: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"sunshine:{source_path}:{content_sha256}"))
