"""Lightweight content-class probes for inventory confidence checks."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from pypdf import PdfReader

from sunshine_core.models import (
    ContentClassProbeAuditSummary,
    ContentClassProbeResult,
    ContentClassTransition,
    ExtractionQuality,
    FileContentClass,
)


PROBE_EXTRACTOR_NAME = "sunshine-content-class-probe"
PROBE_EXTRACTOR_VERSION = "v1"
MAX_SUMMARY_SAMPLES = 25
DEFAULT_MAX_PDF_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_IMAGE_BYTES = 250 * 1024 * 1024
DEFAULT_MAX_TIFF_BYTES = 50 * 1024 * 1024

PDF_EXTENSIONS = {"pdf"}
IMAGE_EXTENSIONS = {"avif", "gif", "heic", "jpeg", "jpg", "png", "webp"}
TIFF_EXTENSIONS = {"tif", "tiff"}
UNKNOWN_REVIEW_HANDLERS = {
    "mov": "video_review",
    "mp4": "video_review",
    "pub": "publisher_file_review",
    "url": "shortcut_review",
    "xlsm": "macro_enabled_spreadsheet_review",
    "zip": "archive_review",
    "": "extensionless_file_review",
}
SCAN_PATH_HINTS = {
    "articles of incorporation",
    "central history",
    "correspondence",
    "current_governing_documents",
    "dental clinics",
    "dental support",
    "index cards",
    "mailing list",
    "minutes",
    "receipts",
    "records",
    "rendered-pages",
    "scholarship",
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


def run_probe_manifest(
    manifest_path: str | Path,
    *,
    results_path: str | Path,
    summary_path: str | Path,
    probe_run_id: str | None = None,
    limit: int | None = None,
    max_pdf_bytes: int = DEFAULT_MAX_PDF_BYTES,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    max_tiff_bytes: int = DEFAULT_MAX_TIFF_BYTES,
    workers: int = 8,
) -> ContentClassProbeAuditSummary:
    generated_at = datetime.now(UTC)
    resolved_probe_run_id = probe_run_id or _default_probe_run_id(generated_at)
    manifest = Path(manifest_path)
    results = Path(results_path)
    summary = Path(summary_path)

    results.parent.mkdir(parents=True, exist_ok=True)
    counters: Counter[str] = Counter()
    skipped_by_reason: Counter[str] = Counter()
    by_transition: Counter[str] = Counter()
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    inventory_run_id: str | None = None

    manifest_rows = _read_manifest_rows(manifest, limit)
    if manifest_rows:
        inventory_run_id = str(manifest_rows[0]["inventory_run_id"])

    with results.open("w", encoding="utf-8") as output_file:
        if workers <= 1:
            for manifest_row in manifest_rows:
                result = _probe_row_with_limits(
                    manifest_row,
                    resolved_probe_run_id,
                    max_pdf_bytes=max_pdf_bytes,
                    max_image_bytes=max_image_bytes,
                    max_tiff_bytes=max_tiff_bytes,
                )
                _write_result(output_file, result, counters, skipped_by_reason, by_transition, samples)
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(
                        _probe_row_with_limits,
                        manifest_row,
                        resolved_probe_run_id,
                        max_pdf_bytes=max_pdf_bytes,
                        max_image_bytes=max_image_bytes,
                        max_tiff_bytes=max_tiff_bytes,
                    )
                    for manifest_row in manifest_rows
                ]
                for future in as_completed(futures):
                    result = future.result()
                    _write_result(output_file, result, counters, skipped_by_reason, by_transition, samples)

    audit_summary = ContentClassProbeAuditSummary(
        inventory_run_id=inventory_run_id or "unknown",
        probe_run_id=resolved_probe_run_id,
        generated_at=generated_at,
        total_probe_candidates=counters["total_probe_candidates"],
        unchanged_classifications=counters["unchanged_classifications"],
        changed_classifications=counters["changed_classifications"],
        failed_extractions=counters["failed_extractions"],
        empty_or_poor_extractions=counters["empty_or_poor_extractions"],
        still_unknown=counters["still_unknown"],
        review_required=counters["review_required"],
        skipped_files=counters["skipped_files"],
        skipped_by_reason=dict(sorted(skipped_by_reason.items())),
        by_transition=dict(sorted(by_transition.items())),
        samples={key: value for key, value in sorted(samples.items())},
    )

    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(audit_summary.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit_summary


def _read_manifest_rows(manifest: Path, limit: int | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with manifest.open("r", encoding="utf-8") as input_file:
        for line in input_file:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _probe_row_with_limits(
    manifest_row: dict[str, Any],
    probe_run_id: str,
    *,
    max_pdf_bytes: int,
    max_image_bytes: int,
    max_tiff_bytes: int,
) -> ContentClassProbeResult:
    return probe_manifest_row(
        manifest_row,
        probe_run_id,
        max_pdf_bytes=max_pdf_bytes,
        max_image_bytes=max_image_bytes,
        max_tiff_bytes=max_tiff_bytes,
    )


def _write_result(
    output_file: TextIO,
    result: ContentClassProbeResult,
    counters: Counter[str],
    skipped_by_reason: Counter[str],
    by_transition: Counter[str],
    samples: dict[str, list[dict[str, Any]]],
) -> None:
    _write_jsonl(output_file, result.model_dump(mode="json"))
    _note_result(result, counters, skipped_by_reason, by_transition, samples)


def probe_manifest_row(
    manifest_row: dict[str, Any],
    probe_run_id: str,
    *,
    max_pdf_bytes: int = DEFAULT_MAX_PDF_BYTES,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    max_tiff_bytes: int = DEFAULT_MAX_TIFF_BYTES,
) -> ContentClassProbeResult:
    source_path = Path(manifest_row["source_path"])
    before_class = FileContentClass(manifest_row["content_class"])
    extension = str(manifest_row.get("extension") or "").lower()

    if not source_path.exists():
        return _result(
            manifest_row,
            probe_run_id,
            status="failed",
            before_class=before_class,
            after_class=before_class,
            transition_reason="source_missing",
            extraction_quality=ExtractionQuality.POOR,
            confidence_after=0.0,
            requires_review=True,
            review_reasons=["source_missing"],
            warnings=["Source path does not exist at probe time."],
            metadata={"source_exists": False},
        )

    try:
        if extension in PDF_EXTENSIONS:
            if _too_large_for_probe(manifest_row, max_pdf_bytes):
                return _too_large_result(manifest_row, probe_run_id, before_class, "pdf_too_large_for_lightweight_probe")
            return _probe_pdf(manifest_row, probe_run_id, source_path, before_class)
        if extension in TIFF_EXTENSIONS:
            if _too_large_for_probe(manifest_row, max_tiff_bytes):
                return _too_large_result(manifest_row, probe_run_id, before_class, "tiff_too_large_for_lightweight_probe")
            return _probe_tiff(manifest_row, probe_run_id, source_path, before_class)
        if extension in IMAGE_EXTENSIONS:
            if _too_large_for_probe(manifest_row, max_image_bytes):
                return _too_large_result(manifest_row, probe_run_id, before_class, "image_too_large_for_lightweight_probe")
            return _probe_image(manifest_row, probe_run_id, source_path, before_class)
        return _probe_deferred_or_unknown(manifest_row, probe_run_id, before_class, extension)
    except (OSError, ValidationError, ValueError) as error:
        return _result(
            manifest_row,
            probe_run_id,
            status="failed",
            before_class=before_class,
            after_class=before_class,
            transition_reason="probe_failed",
            extraction_quality=ExtractionQuality.POOR,
            confidence_after=0.0,
            requires_review=True,
            review_reasons=["probe_failed"],
            warnings=[str(error)],
            metadata={"source_exists": True, "exception_type": type(error).__name__},
        )


def _probe_pdf(
    manifest_row: dict[str, Any],
    probe_run_id: str,
    source_path: Path,
    before_class: FileContentClass,
) -> ContentClassProbeResult:
    try:
        reader = PdfReader(str(source_path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as error:  # pypdf exposes several encryption failure paths.
                return _result(
                    manifest_row,
                    probe_run_id,
                    status="failed",
                    before_class=before_class,
                    after_class=before_class,
                    transition_reason="pdf_encrypted_or_locked",
                    extraction_quality=ExtractionQuality.POOR,
                    confidence_after=0.0,
                    requires_review=True,
                    review_reasons=["pdf_encrypted_or_locked"],
                    warnings=[str(error)],
                    metadata={"encrypted": True},
                )
        page_count = len(reader.pages)
        sampled_pages = min(page_count, 3)
        text_parts: list[str] = []
        for page in reader.pages[:sampled_pages]:
            text_parts.append(page.extract_text() or "")
        extracted_text_chars = len("".join(text_parts).strip())
    except Exception as error:
        return _result(
            manifest_row,
            probe_run_id,
            status="failed",
            before_class=before_class,
            after_class=before_class,
            transition_reason="pdf_probe_failed",
            extraction_quality=ExtractionQuality.POOR,
            confidence_after=0.0,
            requires_review=True,
            review_reasons=["pdf_probe_failed"],
            warnings=[str(error)],
            metadata={"exception_type": type(error).__name__},
        )

    metadata = {
        "page_count": page_count,
        "sampled_pages": sampled_pages,
        "sample_text_chars": extracted_text_chars,
        "encrypted": False,
    }
    if page_count == 0:
        return _result(
            manifest_row,
            probe_run_id,
            status="failed",
            before_class=before_class,
            after_class=before_class,
            transition_reason="pdf_has_no_pages",
            extraction_quality=ExtractionQuality.EMPTY,
            confidence_after=0.0,
            requires_review=True,
            review_reasons=["pdf_has_no_pages"],
            metadata=metadata,
        )
    if extracted_text_chars >= 100:
        return _result(
            manifest_row,
            probe_run_id,
            status="probed",
            before_class=before_class,
            after_class=FileContentClass.DOCUMENT,
            transition_reason="pdf_extractable_text_detected",
            extraction_quality=ExtractionQuality.OK,
            confidence_after=0.94,
            requires_review=False,
            metadata=metadata,
        )
    if extracted_text_chars > 0:
        return _result(
            manifest_row,
            probe_run_id,
            status="probed",
            before_class=before_class,
            after_class=FileContentClass.DOCUMENT,
            transition_reason="pdf_sparse_text_requires_review",
            extraction_quality=ExtractionQuality.POOR,
            confidence_after=0.68,
            requires_review=True,
            review_reasons=["pdf_sparse_text"],
            metadata=metadata,
        )
    return _result(
        manifest_row,
        probe_run_id,
        status="probed",
        before_class=before_class,
        after_class=FileContentClass.SCANNED_DOCUMENT,
        transition_reason="pdf_image_only_or_empty_text",
        extraction_quality=ExtractionQuality.OK,
        confidence_after=0.88,
        requires_review=False,
        metadata=metadata,
    )


def _probe_tiff(
    manifest_row: dict[str, Any],
    probe_run_id: str,
    source_path: Path,
    before_class: FileContentClass,
) -> ContentClassProbeResult:
    try:
        with Image.open(source_path) as image:
            metadata = _image_metadata(image)
    except UnidentifiedImageError as error:
        return _result(
            manifest_row,
            probe_run_id,
            status="failed",
            before_class=before_class,
            after_class=before_class,
            transition_reason="tiff_unreadable",
            extraction_quality=ExtractionQuality.POOR,
            confidence_after=0.0,
            requires_review=True,
            review_reasons=["tiff_unreadable"],
            warnings=[str(error)],
            metadata={"exception_type": type(error).__name__},
        )

    metadata["ocr_eligible"] = True
    return _result(
        manifest_row,
        probe_run_id,
        status="probed",
        before_class=before_class,
        after_class=FileContentClass.SCANNED_DOCUMENT,
        transition_reason="tiff_readable_document_image",
        extraction_quality=ExtractionQuality.OK,
        confidence_after=0.92,
        requires_review=False,
        metadata=metadata,
    )


def _probe_image(
    manifest_row: dict[str, Any],
    probe_run_id: str,
    source_path: Path,
    before_class: FileContentClass,
) -> ContentClassProbeResult:
    try:
        with Image.open(source_path) as image:
            metadata = _image_metadata(image)
    except UnidentifiedImageError as error:
        after_class, transition_reason = _image_policy_class(manifest_row, before_class, unreadable=True)
        return _result(
            manifest_row,
            probe_run_id,
            status="failed",
            before_class=before_class,
            after_class=after_class,
            transition_reason=transition_reason,
            extraction_quality=ExtractionQuality.POOR,
            confidence_after=0.5,
            requires_review=False,
            warnings=[str(error)],
            metadata={
                "exception_type": type(error).__name__,
                "technical_retry_required": True,
                "human_review_required": False,
            },
        )

    reasons = set(manifest_row.get("reasons") or [])
    metadata["ocr_eligible"] = _ocr_eligible(metadata)
    policy_class, policy_reason = _image_policy_class(manifest_row, before_class)
    if policy_class == FileContentClass.SCANNED_DOCUMENT or "image_scan_path_hint" in reasons:
        return _result(
            manifest_row,
            probe_run_id,
            status="probed",
            before_class=before_class,
            after_class=FileContentClass.SCANNED_DOCUMENT,
            transition_reason=policy_reason,
            extraction_quality=ExtractionQuality.OK,
            confidence_after=0.86,
            requires_review=False,
            metadata=metadata,
        )
    if policy_class == FileContentClass.IMAGE or metadata.get("captured_at") or "photo_path_hint" in reasons:
        return _result(
            manifest_row,
            probe_run_id,
            status="probed",
            before_class=before_class,
            after_class=FileContentClass.IMAGE,
            transition_reason=policy_reason,
            extraction_quality=ExtractionQuality.OK,
            confidence_after=0.88,
            requires_review=False,
            metadata=metadata,
        )
    return _result(
        manifest_row,
        probe_run_id,
        status="probed",
        before_class=before_class,
        after_class=FileContentClass.IMAGE,
        transition_reason="generic_readable_image_accepted_by_policy",
        extraction_quality=ExtractionQuality.OK,
        confidence_after=0.82,
        requires_review=False,
        metadata=metadata,
    )


def _probe_deferred_or_unknown(
    manifest_row: dict[str, Any],
    probe_run_id: str,
    before_class: FileContentClass,
    extension: str,
) -> ContentClassProbeResult:
    handler = UNKNOWN_REVIEW_HANDLERS.get(extension, "unsupported_binary_review")
    after_class = before_class
    if extension == "xlsm":
        after_class = FileContentClass.SPREADSHEET
    metadata = {
        "deferred_handler": handler,
        "source_exists": True,
    }
    return _result(
        manifest_row,
        probe_run_id,
        status="probed",
        before_class=before_class,
        after_class=after_class,
        transition_reason=handler,
        extraction_quality=ExtractionQuality.POOR,
        confidence_after=0.55 if after_class != before_class else 0.4,
        requires_review=True,
        review_reasons=[handler],
        metadata=metadata,
    )


def _too_large_for_probe(manifest_row: dict[str, Any], max_bytes: int) -> bool:
    size_bytes = manifest_row.get("size_bytes")
    return size_bytes is not None and int(size_bytes) > max_bytes


def _too_large_result(
    manifest_row: dict[str, Any],
    probe_run_id: str,
    before_class: FileContentClass,
    review_reason: str,
) -> ContentClassProbeResult:
    after_class, transition_reason = _image_policy_class(manifest_row, before_class)
    if review_reason == "image_too_large_for_lightweight_probe" and after_class in {
        FileContentClass.IMAGE,
        FileContentClass.SCANNED_DOCUMENT,
    }:
        return _result(
            manifest_row,
            probe_run_id,
            status="probed",
            before_class=before_class,
            after_class=after_class,
            transition_reason=f"{transition_reason}_large_file",
            extraction_quality=ExtractionQuality.OK,
            confidence_after=0.8,
            requires_review=False,
            metadata={
                "size_bytes": manifest_row.get("size_bytes"),
                "lightweight_probe_skipped": True,
                "accepted_by_policy": True,
                "source_exists": True,
            },
        )
    return _result(
        manifest_row,
        probe_run_id,
        status="probed",
        before_class=before_class,
        after_class=before_class,
        transition_reason=review_reason,
        extraction_quality=ExtractionQuality.POOR,
        confidence_after=0.5,
        requires_review=True,
        review_reasons=[review_reason],
        metadata={
            "size_bytes": manifest_row.get("size_bytes"),
            "lightweight_probe_skipped": True,
            "source_exists": True,
        },
    )


def _image_policy_class(
    manifest_row: dict[str, Any],
    before_class: FileContentClass,
    *,
    unreadable: bool = False,
) -> tuple[FileContentClass, str]:
    relative_path = str(manifest_row.get("relative_path") or "").lower()
    name = str(manifest_row.get("name") or "").lower()
    reasons = set(manifest_row.get("reasons") or [])
    if before_class == FileContentClass.SCANNED_DOCUMENT or "image_scan_path_hint" in reasons:
        return FileContentClass.SCANNED_DOCUMENT, "image_scan_evidence_confirmed"
    if _has_hint(relative_path, SCAN_PATH_HINTS) or _looks_like_rendered_page(name):
        return FileContentClass.SCANNED_DOCUMENT, "image_scan_policy_path_or_name"
    if "photo_path_hint" in reasons or _has_hint(relative_path, PHOTO_PATH_HINTS):
        return FileContentClass.IMAGE, "photo_policy_path_confirmed"
    if unreadable:
        return before_class, "image_unreadable_technical_retry"
    return FileContentClass.IMAGE, "generic_readable_image_accepted_by_policy"


def _has_hint(path_text: str, hints: set[str]) -> bool:
    return any(hint in path_text for hint in hints)


def _looks_like_rendered_page(name: str) -> bool:
    return name.startswith("page-") or name.startswith("scan") or "_docs_" in name or "_history_" in name


def _image_metadata(image: Image.Image) -> dict[str, Any]:
    width, height = image.size
    captured_at = None
    try:
        exif = image.getexif()
    except (AttributeError, OSError):
        exif = {}
    for tag in (36867, 36868, 306):
        value = exif.get(tag) if exif else None
        if value:
            captured_at = str(value)
            break
    return {
        "image_format": image.format,
        "width": width,
        "height": height,
        "mode": image.mode,
        "frame_count": getattr(image, "n_frames", 1),
        "captured_at": captured_at,
    }


def _ocr_eligible(metadata: dict[str, Any]) -> bool:
    width = int(metadata.get("width") or 0)
    height = int(metadata.get("height") or 0)
    return width >= 600 and height >= 600


def _result(
    manifest_row: dict[str, Any],
    probe_run_id: str,
    *,
    status: str,
    before_class: FileContentClass,
    after_class: FileContentClass,
    transition_reason: str,
    extraction_quality: ExtractionQuality,
    confidence_after: float,
    requires_review: bool,
    review_reasons: list[str] | None = None,
    warnings: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ContentClassProbeResult:
    metadata = metadata or {}
    warnings = warnings or []
    review_reasons = review_reasons or []
    transition = ContentClassTransition(
        source_path=manifest_row["source_path"],
        inventory_run_id=manifest_row["inventory_run_id"],
        before_class=before_class,
        after_class=after_class,
        transition_reason=transition_reason,
        extractor_name=PROBE_EXTRACTOR_NAME,
        extractor_version=PROBE_EXTRACTOR_VERSION,
        extraction_quality=extraction_quality,
        warnings=warnings,
        requires_review=requires_review,
        metadata=metadata,
    )
    return ContentClassProbeResult(
        inventory_run_id=manifest_row["inventory_run_id"],
        probe_run_id=probe_run_id,
        source_path=manifest_row["source_path"],
        relative_path=manifest_row["relative_path"],
        status=status,  # type: ignore[arg-type]
        before_class=before_class,
        after_class=after_class,
        transition_reason=transition_reason,
        extractor_name=PROBE_EXTRACTOR_NAME,
        extractor_version=PROBE_EXTRACTOR_VERSION,
        extraction_quality=extraction_quality,
        confidence_after=confidence_after,
        requires_review=requires_review,
        review_reasons=review_reasons,
        warnings=warnings,
        metadata=metadata,
        transition=transition,
    )


def _note_result(
    result: ContentClassProbeResult,
    counters: Counter[str],
    skipped_by_reason: Counter[str],
    by_transition: Counter[str],
    samples: dict[str, list[dict[str, Any]]],
) -> None:
    counters["total_probe_candidates"] += 1
    transition_key = f"{result.before_class.value}->{result.after_class.value}"
    by_transition[transition_key] += 1

    if result.status == "failed":
        counters["failed_extractions"] += 1
        _append_sample(samples["failed_extractions"], result)
    if result.before_class == result.after_class:
        counters["unchanged_classifications"] += 1
    else:
        counters["changed_classifications"] += 1
        _append_sample(samples["changed_classifications"], result)
    if result.extraction_quality in {ExtractionQuality.EMPTY, ExtractionQuality.POOR}:
        counters["empty_or_poor_extractions"] += 1
        _append_sample(samples["empty_or_poor_extractions"], result)
    if result.after_class == FileContentClass.BINARY_OR_UNKNOWN:
        counters["still_unknown"] += 1
        _append_sample(samples["still_unknown"], result)
    if result.requires_review:
        counters["review_required"] += 1
        _append_sample(samples["review_required"], result)
    for reason in result.review_reasons:
        if reason.startswith("skip_"):
            counters["skipped_files"] += 1
            skipped_by_reason[reason] += 1


def _append_sample(samples: list[dict[str, Any]], result: ContentClassProbeResult) -> None:
    if len(samples) >= MAX_SUMMARY_SAMPLES:
        return
    samples.append(
        {
            "relative_path": result.relative_path,
            "before_class": result.before_class.value,
            "after_class": result.after_class.value,
            "transition_reason": result.transition_reason,
            "requires_review": result.requires_review,
            "review_reasons": result.review_reasons,
        }
    )


def _write_jsonl(output: TextIO, payload: dict[str, Any]) -> None:
    output.write(json.dumps(payload, sort_keys=True))
    output.write("\n")


def _default_probe_run_id(generated_at: datetime) -> str:
    compact_timestamp = generated_at.isoformat().replace("-", "").replace(":", "").split(".")[0]
    return f"probe-{compact_timestamp}Z"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run lightweight content-class probes from a probe manifest.")
    parser.add_argument("manifest", type=Path, help="Probe manifest JSONL produced by the inventory command.")
    parser.add_argument("--results", type=Path, required=True, help="Write probe result JSONL to this path.")
    parser.add_argument("--summary", type=Path, required=True, help="Write probe summary JSON to this path.")
    parser.add_argument("--probe-run-id", help="Stable probe run ID for all result rows.")
    parser.add_argument("--limit", type=int, help="Process only the first N manifest rows.")
    parser.add_argument("--max-pdf-bytes", type=int, default=DEFAULT_MAX_PDF_BYTES)
    parser.add_argument("--max-image-bytes", type=int, default=DEFAULT_MAX_IMAGE_BYTES)
    parser.add_argument("--max-tiff-bytes", type=int, default=DEFAULT_MAX_TIFF_BYTES)
    parser.add_argument("--workers", type=int, default=8, help="Number of parallel file probe workers.")
    args = parser.parse_args()

    run_probe_manifest(
        args.manifest,
        results_path=args.results,
        summary_path=args.summary,
        probe_run_id=args.probe_run_id,
        limit=args.limit,
        max_pdf_bytes=args.max_pdf_bytes,
        max_image_bytes=args.max_image_bytes,
        max_tiff_bytes=args.max_tiff_bytes,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
