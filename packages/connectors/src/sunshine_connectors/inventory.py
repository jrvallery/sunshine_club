"""Filesystem inventory for the Phase 1 NAS corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from sunshine_core.models import FileContentClass, SourceCollection, SourceType, StagedFileRecord


SUNSHINE_ROOT = Path("/mnt/sunshine")
LOW_CONFIDENCE_THRESHOLD = 0.8
MAX_SUMMARY_SAMPLES = 25

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
IMAGE_EXTENSIONS = {"avif", "gif", "heic", "jpeg", "jpg", "png", "tif", "tiff", "webp"}
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

SKIP_DIRECTORY_NAMES = {
    "#recycle",
    ".cache",
    ".documentrevisions-v100",
    ".fseventsd",
    ".git",
    ".hg",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".spotlight-v100",
    ".svn",
    ".sync",
    ".temporaryitems",
    ".trashes",
    "__macosx",
    "__pycache__",
    "@eadir",
    "temp",
    "tmp",
    "node_modules",
}

SKIP_FILE_NAMES = {
    ".ds_store",
    "desktop.ini",
    "ehthumbs.db",
    "thumbs.db",
}

SKIP_FILE_SUFFIXES = {
    ".crdownload",
    ".download",
    ".lock",
    ".part",
    ".pyc",
    ".swo",
    ".swp",
    ".temp",
    ".tmp",
}

EXTRACTION_PROBE_REASONS = {
    "pdf_needs_text_probe",
    "image_extension_needs_probe",
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


@dataclass(frozen=True)
class SkipDecision:
    should_skip: bool
    reason: str | None = None


@dataclass
class InventoryRunSummary:
    root: str
    output_path: str | None
    limit: int | None
    checksum_requested: bool
    checksum_max_bytes: int | None
    low_confidence_threshold: float
    generated_at: str
    scanned_files: int = 0
    emitted_files: int = 0
    skipped_files: int = 0

    def __post_init__(self) -> None:
        self.by_source_collection: Counter[str] = Counter()
        self.by_content_class: Counter[str] = Counter()
        self.by_extension: Counter[str] = Counter()
        self.skipped_by_reason: Counter[str] = Counter()
        self.low_confidence_count = 0
        self.extraction_probe_count = 0
        self.low_confidence_samples: list[dict[str, object]] = []
        self.binary_or_unknown_samples: list[dict[str, object]] = []
        self.extraction_probe_samples: list[dict[str, object]] = []

    def note_skipped(self, path: Path, root: Path, reason: str) -> None:
        self.skipped_files += 1
        self.skipped_by_reason[reason] += 1

    def note_record(self, record: StagedFileRecord) -> None:
        self.emitted_files += 1
        self.by_source_collection[record.source_collection.value] += 1
        self.by_content_class[record.content_class.value] += 1
        self.by_extension[record.extension or "[none]"] += 1

        initial_class = record.raw_metadata["initial_content_class"]
        confidence = float(initial_class["confidence"])
        reasons = list(initial_class["reasons"])
        sample = _summary_sample(record, confidence, reasons)

        if confidence < self.low_confidence_threshold:
            self.low_confidence_count += 1
            _append_sample(self.low_confidence_samples, sample)
        if record.content_class == FileContentClass.BINARY_OR_UNKNOWN:
            _append_sample(self.binary_or_unknown_samples, sample)
        if any(reason in EXTRACTION_PROBE_REASONS for reason in reasons):
            self.extraction_probe_count += 1
            _append_sample(self.extraction_probe_samples, sample)

    def as_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "root": self.root,
            "output_path": self.output_path,
            "limit": self.limit,
            "checksum_requested": self.checksum_requested,
            "checksum_max_bytes": self.checksum_max_bytes,
            "low_confidence_threshold": self.low_confidence_threshold,
            "scanned_files": self.scanned_files,
            "emitted_files": self.emitted_files,
            "skipped_files": self.skipped_files,
            "by_source_collection": dict(sorted(self.by_source_collection.items())),
            "by_content_class": dict(sorted(self.by_content_class.items())),
            "by_extension": dict(sorted(self.by_extension.items())),
            "skipped_by_reason": dict(sorted(self.skipped_by_reason.items())),
            "low_confidence": {
                "count": self.low_confidence_count,
                "sample_limit": MAX_SUMMARY_SAMPLES,
                "samples": self.low_confidence_samples,
            },
            "binary_or_unknown": {
                "count": self.by_content_class.get(FileContentClass.BINARY_OR_UNKNOWN.value, 0),
                "sample_limit": MAX_SUMMARY_SAMPLES,
                "samples": self.binary_or_unknown_samples,
            },
            "needs_extraction_probe": {
                "count": self.extraction_probe_count,
                "sample_limit": MAX_SUMMARY_SAMPLES,
                "samples": self.extraction_probe_samples,
            },
        }


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
        skip_decision = should_skip_path(path, root_path)
        if skip_decision.should_skip:
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


def write_inventory(
    root: str | Path = SUNSHINE_ROOT,
    *,
    output_path: str | Path | None = None,
    summary_path: str | Path | None = None,
    limit: int | None = None,
    compute_checksum: bool = False,
    checksum_max_bytes: int | None = None,
    low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
) -> InventoryRunSummary:
    root_path = Path(root)
    resolved_output_path = Path(output_path) if output_path is not None else None
    resolved_summary_path = Path(summary_path) if summary_path is not None else None
    excluded_paths = _excluded_output_paths(resolved_output_path, resolved_summary_path)
    summary = InventoryRunSummary(
        root=str(root_path),
        output_path=str(resolved_output_path) if resolved_output_path else None,
        limit=limit,
        checksum_requested=compute_checksum,
        checksum_max_bytes=checksum_max_bytes,
        low_confidence_threshold=low_confidence_threshold,
        generated_at=datetime.now(UTC).isoformat(),
    )

    if resolved_output_path is None:
        _write_inventory_records(
            sys.stdout,
            root_path,
            summary,
            excluded_paths,
            limit=limit,
            compute_checksum=compute_checksum,
            checksum_max_bytes=checksum_max_bytes,
        )
    else:
        resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
        with resolved_output_path.open("w", encoding="utf-8") as output:
            _write_inventory_records(
                output,
                root_path,
                summary,
                excluded_paths,
                limit=limit,
                compute_checksum=compute_checksum,
                checksum_max_bytes=checksum_max_bytes,
            )

    if resolved_summary_path is not None:
        resolved_summary_path.parent.mkdir(parents=True, exist_ok=True)
        with resolved_summary_path.open("w", encoding="utf-8") as output:
            json.dump(summary.as_dict(), output, indent=2, sort_keys=True)
            output.write("\n")

    return summary


def should_skip_path(path: str | Path, root: str | Path = SUNSHINE_ROOT) -> SkipDecision:
    file_path = Path(path)
    parts = _relative_parts(file_path, Path(root))
    lowered_parts = tuple(part.lower() for part in parts)

    for part in lowered_parts[:-1]:
        if part in SKIP_DIRECTORY_NAMES:
            return SkipDecision(True, f"skip_directory:{part}")

    name = file_path.name
    lowered_name = name.lower()
    if lowered_name in SKIP_FILE_NAMES:
        return SkipDecision(True, f"skip_file:{lowered_name}")
    if name.startswith("._"):
        return SkipDecision(True, "skip_file:appledouble")
    if name.startswith(".~lock."):
        return SkipDecision(True, "skip_file:lockfile")
    if name.startswith("~$"):
        return SkipDecision(True, "skip_file:office_temp")
    if lowered_name.endswith(tuple(SKIP_FILE_SUFFIXES)):
        return SkipDecision(True, f"skip_suffix:{Path(lowered_name).suffix}")

    return SkipDecision(False)


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


def _write_inventory_records(
    output: TextIO,
    root_path: Path,
    summary: InventoryRunSummary,
    excluded_paths: set[Path],
    *,
    limit: int | None,
    compute_checksum: bool,
    checksum_max_bytes: int | None,
) -> None:
    for path in root_path.rglob("*"):
        if not path.is_file():
            continue
        if _safe_resolve(path) in excluded_paths:
            continue

        summary.scanned_files += 1
        skip_decision = should_skip_path(path, root_path)
        if skip_decision.should_skip:
            summary.note_skipped(path, root_path, skip_decision.reason or "skip_unknown")
            continue

        record = inventory_file(
            path,
            root_path,
            compute_checksum=compute_checksum,
            checksum_max_bytes=checksum_max_bytes,
        )
        output.write(json.dumps(record.model_dump(mode="json"), sort_keys=True))
        output.write("\n")
        summary.note_record(record)

        if limit is not None and summary.emitted_files >= limit:
            return


def _summary_sample(record: StagedFileRecord, confidence: float, reasons: list[str]) -> dict[str, object]:
    return {
        "relative_path": record.raw_metadata["relative_path"],
        "source_collection": record.source_collection.value,
        "content_class": record.content_class.value,
        "confidence": confidence,
        "reasons": reasons,
    }


def _append_sample(samples: list[dict[str, object]], sample: dict[str, object]) -> None:
    if len(samples) < MAX_SUMMARY_SAMPLES:
        samples.append(sample)


def _excluded_output_paths(*paths: Path | None) -> set[Path]:
    return {_safe_resolve(path) for path in paths if path is not None}


def _safe_resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except FileNotFoundError:
        return path.absolute()


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory the Sunshine Club NAS corpus.")
    parser.add_argument("root", nargs="?", default=str(SUNSHINE_ROOT))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, help="Write inventory JSONL to this file instead of stdout.")
    parser.add_argument("--summary", type=Path, help="Write inventory quality summary JSON to this file.")
    parser.add_argument("--checksum", action="store_true", help="Compute SHA-256 checksums by reading file bytes.")
    parser.add_argument(
        "--checksum-max-bytes",
        type=int,
        help="Only compute checksums for files at or below this size.",
    )
    parser.add_argument(
        "--low-confidence-threshold",
        type=float,
        default=LOW_CONFIDENCE_THRESHOLD,
        help="Content-class confidence below this value is flagged in the summary.",
    )
    args = parser.parse_args()

    write_inventory(
        args.root,
        output_path=args.output,
        summary_path=args.summary,
        limit=args.limit,
        compute_checksum=args.checksum,
        checksum_max_bytes=args.checksum_max_bytes,
        low_confidence_threshold=args.low_confidence_threshold,
    )


if __name__ == "__main__":
    main()
