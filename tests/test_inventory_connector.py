from __future__ import annotations

import hashlib
from pathlib import Path

from sunshine_connectors.inventory import classify_content, infer_source_collection, inventory_file
from sunshine_core.models import FileContentClass, SourceCollection


def _write(root: Path, relative_path: str, content: bytes = b"sample") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_inventory_file_captures_provenance_and_initial_content_class(tmp_path: Path) -> None:
    path = _write(tmp_path, "Sunshine shared folders/Minutes-agendas- dental reports and treasurer reports/2025-2026/scan.tif")

    record = inventory_file(path, tmp_path)

    assert record.source_collection == SourceCollection.SUNSHINE_SHARED_FOLDERS
    assert record.name == "scan.tif"
    assert record.extension == "tif"
    assert record.mime_type == "image/tiff"
    assert record.size_bytes == len(b"sample")
    assert record.content_class == FileContentClass.SCANNED_DOCUMENT
    assert record.checksum is None
    assert record.raw_metadata["checksum"]["status"] == "not_requested"
    assert record.raw_metadata["relative_path"] == (
        "Sunshine shared folders/Minutes-agendas- dental reports and treasurer reports/2025-2026/scan.tif"
    )
    assert record.raw_metadata["initial_content_class"]["reasons"]


def test_source_collection_from_top_level_corpus_area(tmp_path: Path) -> None:
    assert (
        infer_source_collection(tmp_path / "From Mac Sunshine Pass 2026-05-25/SUMMARY.md", tmp_path)
        == SourceCollection.FROM_MAC_PASS
    )
    assert (
        infer_source_collection(tmp_path / "google-drive-delta-2026-05-25/Sunshine/file.pdf", tmp_path)
        == SourceCollection.GOOGLE_DRIVE_DELTA
    )
    assert infer_source_collection(tmp_path / "_manifest/run/summary.json", tmp_path) == SourceCollection.MANIFEST


def test_inventory_file_computes_checksum_when_requested(tmp_path: Path) -> None:
    content = b"sample"
    path = _write(tmp_path, "Sunshine shared folders/Admin Docs/sample.txt", content)

    record = inventory_file(path, tmp_path, compute_checksum=True)

    assert record.checksum == hashlib.sha256(content).hexdigest()
    assert record.raw_metadata["checksum"]["algorithm"] == "sha256"
    assert record.raw_metadata["checksum"]["status"] == "computed"


def test_inventory_file_respects_checksum_size_limit(tmp_path: Path) -> None:
    path = _write(tmp_path, "Sunshine shared folders/Admin Docs/sample.txt", b"sample")

    record = inventory_file(path, tmp_path, compute_checksum=True, checksum_max_bytes=3)

    assert record.checksum is None
    assert record.raw_metadata["checksum"]["status"] == "skipped_size_limit"
    assert record.raw_metadata["checksum"]["max_bytes"] == 3


def test_manifest_path_becomes_manifest_content_class(tmp_path: Path) -> None:
    path = tmp_path / "_manifest/2026-05-25T1205MDT-sunshine-inventory/google_drive_full_inventory.jsonl"

    decision = classify_content(path, tmp_path)

    assert decision.content_class == FileContentClass.MANIFEST
    assert "manifest_path" in decision.reasons


def test_historical_photo_path_becomes_image(tmp_path: Path) -> None:
    path = tmp_path / "Sunshine shared folders/Historical Photos/Photos to share/member.jpg"

    decision = classify_content(path, tmp_path)

    assert decision.content_class == FileContentClass.IMAGE
    assert "photo_path_hint" in decision.reasons


def test_minutes_image_path_becomes_scanned_document(tmp_path: Path) -> None:
    path = tmp_path / "Sunshine shared folders/Minutes-agendas- dental reports and treasurer reports/1902-1949/page.jpeg"

    decision = classify_content(path, tmp_path)

    assert decision.content_class == FileContentClass.SCANNED_DOCUMENT
    assert "image_scan_path_hint" in decision.reasons


def test_office_and_email_extensions_get_specific_classes(tmp_path: Path) -> None:
    assert classify_content(tmp_path / "Sunshine shared folders/Mailing list/list.xlsx", tmp_path).content_class == (
        FileContentClass.SPREADSHEET
    )
    assert classify_content(tmp_path / "Sunshine shared folders/Correspondence/message.eml", tmp_path).content_class == (
        FileContentClass.EMAIL
    )
    assert classify_content(tmp_path / "Sunshine shared folders/Anniversaries/deck.pptx", tmp_path).content_class == (
        FileContentClass.PRESENTATION
    )


def test_paige_workspace_code_becomes_workspace_artifact(tmp_path: Path) -> None:
    path = tmp_path / "Paige Agent Sunshine Files/source-path-snapshot/mnt/agents/paige/tool.py"

    decision = classify_content(path, tmp_path)

    assert decision.content_class == FileContentClass.CODE_OR_WORKSPACE_ARTIFACT
    assert "paige_workspace_file" in decision.reasons


def test_pdf_uses_path_hints_until_pdf_text_probe_exists(tmp_path: Path) -> None:
    minutes_pdf = tmp_path / "Sunshine shared folders/Minutes-agendas- dental reports and treasurer reports/2025.pdf"
    generic_pdf = tmp_path / "Sunshine shared folders/Admin Docs/Sunshine Club Digital Resources.pdf"

    assert classify_content(minutes_pdf, tmp_path).content_class == FileContentClass.SCANNED_DOCUMENT
    generic_decision = classify_content(generic_pdf, tmp_path)

    assert generic_decision.content_class == FileContentClass.DOCUMENT
    assert "pdf_needs_text_probe" in generic_decision.reasons
