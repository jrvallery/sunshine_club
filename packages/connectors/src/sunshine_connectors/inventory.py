"""Filesystem inventory for the Phase 1 NAS corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sunshine_core.models import FileContentClass, SourceCollection, SourceType, StagedFileRecord


SUNSHINE_ROOT = Path("/mnt/sunshine")

SOURCE_COLLECTION_BY_TOP_LEVEL = {
    "Sunshine shared folders": SourceCollection.SUNSHINE_SHARED_FOLDERS,
    "From Mac Sunshine Pass 2026-05-25": SourceCollection.FROM_MAC_PASS,
    "Paige Agent Sunshine Files": SourceCollection.PAIGE_AGENT_FILES,
    "google-drive-delta-2026-05-25": SourceCollection.GOOGLE_DRIVE_DELTA,
    "archive-2026-05-25": SourceCollection.ARCHIVE,
    "_manifest": SourceCollection.MANIFEST,
}

DOCUMENT_EXTENSIONS = {
    "doc",
    "docx",
    "html",
    "htm",
    "md",
    "odt",
    "rtf",
    "txt",
}
SPREADSHEET_EXTENSIONS = {"csv", "tsv", "xls", "xlsx", "ods"}
PRESENTATION_EXTENSIONS = {"ppt", "pptx", "odp"}
EMAIL_EXTENSIONS = {"eml", "msg"}
IMAGE_EXTENSIONS = {"avif", "gif", "heic", "jpeg", "jpg", "png", "tif", "tiff"}
SCANNED_DOCUMENT_EXTENSIONS = {"tif", "tiff"}
MANIFEST_EXTENSIONS = {"json", "jsonl", "log", "nul", "tsv", "csv"}
CODE_OR_WORKSPACE_EXTENSIONS = {
    "bak",
    "conf",
    "example",
    "gitignore",
    "js",
    "json",
    "jsonl",
    "py",
    "pyc",
    "sh",
    "sql",
    "skill",
    "toml",
    "ts",
    "tsx",
    "tmp",
    "yaml",
    "yml",
}

SCAN_PATH_HINTS = {
    "articles of incorporation",
    "archives",
    "central history",
    "current_governing_documents",
    "dental clinics",
    "dental support",
    "history book",
    "index cards",
    "mailing list",
    "minutes",
    "name tags",
    "receipts",
    "records",
    "rescan",
    "scrapbooks",
    "transcription",
    "treasurer",
    "tributes and obituaries",
}

PHOTO_PATH_HINTS = {
    "anniversaries",
    "event photos",
    "historical photos",
    "meeting and event photos",
    "members and friends in the spotlight",
    "photos to share",
}


@dataclass(frozen=True)
class ContentClassDecision:
    content_class: FileContentClass
    confidence: float
    reasons: tuple[str, ...]


def iter_inventory(
    root: str | Path = SUNSHINE_ROOT,
    *,
    limit: int | None = None,
    compute_checksum: bool = False,
    checksum_max_bytes: int | None = None,
) -> Iterator[StagedFileRecord]:
    root_path = Path(root)
    emitted = 0

    for path in root_path.rglob("*"):
        if not path.is_file():
            continue
        yield inventory_file(
            path,
            root_path,
            compute_checksum=compute_checksum,
            checksum_max_bytes=checksum_max_bytes,
        )
        emitted += 1
        if limit is not None and emitted >= limit:
            return


def inventory_file(
    path: str | Path,
    root: str | Path = SUNSHINE_ROOT,
    *,
    compute_checksum: bool = False,
    checksum_max_bytes: int | None = None,
) -> StagedFileRecord:
    file_path = Path(path)
    root_path = Path(root)
    stat = file_path.stat()
    extension = _extension(file_path)
    mime_type = _mime_type(file_path)
    source_collection = infer_source_collection(file_path, root_path)
    decision = classify_content(file_path, root_path, source_collection, mime_type)
    checksum, checksum_metadata = _checksum(file_path, stat.st_size, compute_checksum, checksum_max_bytes)

    return StagedFileRecord(
        source_type=SourceType.NAS,
        source_collection=source_collection,
        source_path=str(file_path),
        name=file_path.name,
        mime_type=mime_type,
        extension=extension or None,
        size_bytes=stat.st_size,
        source_mtime=datetime.fromtimestamp(stat.st_mtime, UTC),
        content_class=decision.content_class,
        checksum=checksum,
        raw_metadata={
            "checksum": checksum_metadata,
            "initial_content_class": {
                "content_class": decision.content_class.value,
                "confidence": decision.confidence,
                "reasons": list(decision.reasons),
            },
            "relative_path": _relative_path(file_path, root_path),
        },
    )


def infer_source_collection(path: str | Path, root: str | Path = SUNSHINE_ROOT) -> SourceCollection:
    file_path = Path(path)
    parts = _relative_parts(file_path, Path(root))
    if not parts:
        return SourceCollection.OTHER
    return SOURCE_COLLECTION_BY_TOP_LEVEL.get(parts[0], SourceCollection.OTHER)


def classify_content(
    path: str | Path,
    root: str | Path = SUNSHINE_ROOT,
    source_collection: SourceCollection | None = None,
    mime_type: str | None = None,
) -> ContentClassDecision:
    file_path = Path(path)
    root_path = Path(root)
    extension = _extension(file_path)
    source_collection = source_collection or infer_source_collection(file_path, root_path)
    mime_type = mime_type or _mime_type(file_path)
    parts = _relative_parts(file_path, root_path)
    path_text = " / ".join(parts).lower()
    reasons: list[str] = [f"extension={extension or '[none]'}", f"mime_type={mime_type}"]

    if "_manifest" in parts or source_collection == SourceCollection.MANIFEST:
        if extension in MANIFEST_EXTENSIONS or file_path.name in {"HASHING_NOT_USED.txt"}:
            return _decision(FileContentClass.MANIFEST, 0.97, reasons, "manifest_path")

    if source_collection == SourceCollection.PAIGE_AGENT_FILES and extension in CODE_OR_WORKSPACE_EXTENSIONS:
        return _decision(FileContentClass.CODE_OR_WORKSPACE_ARTIFACT, 0.88, reasons, "paige_workspace_file")

    if extension in EMAIL_EXTENSIONS:
        return _decision(FileContentClass.EMAIL, 0.95, reasons, "email_extension")

    if extension in SPREADSHEET_EXTENSIONS:
        if "manifest" in path_text or "_manifest" in parts:
            return _decision(FileContentClass.MANIFEST, 0.92, reasons, "manifest_table")
        return _decision(FileContentClass.SPREADSHEET, 0.95, reasons, "spreadsheet_extension")

    if extension in PRESENTATION_EXTENSIONS:
        return _decision(FileContentClass.PRESENTATION, 0.95, reasons, "presentation_extension")

    if extension in DOCUMENT_EXTENSIONS:
        if source_collection in {SourceCollection.ARCHIVE, SourceCollection.PAIGE_AGENT_FILES} and extension in CODE_OR_WORKSPACE_EXTENSIONS:
            return _decision(FileContentClass.CODE_OR_WORKSPACE_ARTIFACT, 0.76, reasons, "workspace_like_text_file")
        return _decision(FileContentClass.DOCUMENT, 0.9, reasons, "document_extension")

    if extension == "pdf":
        if _has_path_hint(path_text, SCAN_PATH_HINTS):
            return _decision(FileContentClass.SCANNED_DOCUMENT, 0.72, reasons, "pdf_scan_path_hint")
        return _decision(FileContentClass.DOCUMENT, 0.62, reasons, "pdf_needs_text_probe")

    if extension in SCANNED_DOCUMENT_EXTENSIONS:
        return _decision(FileContentClass.SCANNED_DOCUMENT, 0.86, reasons, "tiff_scan_default")

    if extension in IMAGE_EXTENSIONS:
        if _has_path_hint(path_text, SCAN_PATH_HINTS):
            return _decision(FileContentClass.SCANNED_DOCUMENT, 0.74, reasons, "image_scan_path_hint")
        if _has_path_hint(path_text, PHOTO_PATH_HINTS):
            return _decision(FileContentClass.IMAGE, 0.82, reasons, "photo_path_hint")
        return _decision(FileContentClass.IMAGE, 0.58, reasons, "image_extension_needs_probe")

    if extension in CODE_OR_WORKSPACE_EXTENSIONS:
        return _decision(FileContentClass.CODE_OR_WORKSPACE_ARTIFACT, 0.82, reasons, "code_or_workspace_extension")

    return _decision(FileContentClass.BINARY_OR_UNKNOWN, 0.35, reasons, "no_deterministic_rule")


def _decision(
    content_class: FileContentClass,
    confidence: float,
    reasons: list[str],
    *additional_reasons: str,
) -> ContentClassDecision:
    return ContentClassDecision(content_class, confidence, tuple([*reasons, *additional_reasons]))


def _extension(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


def _mime_type(path: Path) -> str:
    guessed, _encoding = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _checksum(
    path: Path,
    size_bytes: int,
    compute_checksum: bool,
    checksum_max_bytes: int | None,
) -> tuple[str | None, dict[str, object]]:
    metadata: dict[str, object] = {"algorithm": "sha256"}
    if not compute_checksum:
        metadata["status"] = "not_requested"
        return None, metadata
    if checksum_max_bytes is not None and size_bytes > checksum_max_bytes:
        metadata["status"] = "skipped_size_limit"
        metadata["max_bytes"] = checksum_max_bytes
        return None, metadata

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    metadata["status"] = "computed"
    return digest.hexdigest(), metadata


def _relative_parts(path: Path, root: Path) -> tuple[str, ...]:
    try:
        return path.relative_to(root).parts
    except ValueError:
        return path.parts


def _relative_path(path: Path, root: Path) -> str:
    return "/".join(_relative_parts(path, root))


def _has_path_hint(path_text: str, hints: set[str]) -> bool:
    return any(hint in path_text for hint in hints)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory the Sunshine Club NAS corpus.")
    parser.add_argument("root", nargs="?", default=str(SUNSHINE_ROOT))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--checksum", action="store_true", help="Compute SHA-256 checksums by reading file bytes.")
    parser.add_argument(
        "--checksum-max-bytes",
        type=int,
        help="Only compute checksums for files at or below this size.",
    )
    args = parser.parse_args()

    for record in iter_inventory(
        args.root,
        limit=args.limit,
        compute_checksum=args.checksum,
        checksum_max_bytes=args.checksum_max_bytes,
    ):
        print(json.dumps(record.model_dump(mode="json"), sort_keys=True))


if __name__ == "__main__":
    main()
