from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sunshine_connectors.inventory import (
    classify_content,
    infer_source_collection,
    inventory_file,
    iter_inventory,
    should_skip_path,
    write_inventory,
)
from sunshine_core.models import (
    ContentClassProbeAuditSummary,
    ContentClassTransition,
    ExtractionQuality,
    FileContentClass,
    SourceCollection,
)


GOLDEN_SAMPLES_PATH = Path(__file__).parent / "fixtures" / "inventory_golden_samples.json"


def _write(root: Path, relative_path: str, content: bytes = b"sample") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_inventory_file_captures_provenance_and_initial_content_class(tmp_path: Path) -> None:
    path = _write(tmp_path, "Sunshine shared folders/Minutes-agendas- dental reports and treasurer reports/2025-2026/scan.tif")

    record = inventory_file(path, tmp_path, inventory_run_id="test-run-1")

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
    assert record.raw_metadata["inventory_run_id"] == "test-run-1"
    assert record.raw_metadata["content_class_stage"] == "initial_inventory"
    assert record.raw_metadata["initial_content_class"]["classifier_name"] == "sunshine-inventory-content-classifier"
    assert record.raw_metadata["initial_content_class"]["classifier_version"] == "v1"
    assert record.raw_metadata["initial_content_class"]["rule_id"] == "tiff_scan_default"
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


def test_inventory_skips_known_system_junk(tmp_path: Path) -> None:
    _write(tmp_path, ".DS_Store")
    _write(tmp_path, "#recycle/desktop.ini")
    _write(tmp_path, "Sunshine shared folders/Admin Docs/keep.md")
    _write(tmp_path, "Sunshine shared folders/Admin Docs/~$draft.docx")
    _write(tmp_path, "Sunshine shared folders/Admin Docs/.~lock.sheet.xlsx#")
    _write(tmp_path, "Sunshine shared folders/Admin Docs/page.tmp")
    _write(tmp_path, "Paige Agent Sunshine Files/source-path-snapshot/mnt/agents/paige/tmp/repo/.git/HEAD")

    records = list(iter_inventory(tmp_path))

    assert [record.raw_metadata["relative_path"] for record in records] == [
        "Sunshine shared folders/Admin Docs/keep.md"
    ]


def test_golden_inventory_samples_match_expected_classification() -> None:
    samples = json.loads(GOLDEN_SAMPLES_PATH.read_text(encoding="utf-8"))

    for sample in samples:
        path = Path("/mnt/sunshine") / sample["relative_path"]
        skip_decision = should_skip_path(path)

        assert skip_decision.should_skip is sample["expected_skip"]
        if sample["expected_skip"]:
            assert skip_decision.reason == sample["expected_skip_reason"]
            continue

        source_collection = infer_source_collection(path)
        decision = classify_content(path, source_collection=source_collection)

        assert source_collection.value == sample["expected_source_collection"]
        assert decision.content_class.value == sample["expected_content_class"]
        if expected_reason := sample.get("expected_reason"):
            assert expected_reason in decision.reasons


def test_write_inventory_outputs_jsonl_and_summary(tmp_path: Path) -> None:
    _write(tmp_path, ".DS_Store")
    _write(tmp_path, "#recycle/desktop.ini")
    _write(tmp_path, "Sunshine shared folders/Admin Docs/Sunshine Club Digital Resources.pdf")
    _write(tmp_path, "Sunshine shared folders/Unknown/random.bin")
    _write(tmp_path, "Sunshine shared folders/Unsorted/member.jpg")
    output_path = tmp_path / "_manifest" / "inventory.jsonl"
    summary_path = tmp_path / "_manifest" / "summary.json"
    skipped_audit_path = tmp_path / "_manifest" / "skipped-files.jsonl"
    probe_manifest_path = tmp_path / "_manifest" / "probe-manifest.jsonl"

    summary = write_inventory(
        tmp_path,
        output_path=output_path,
        summary_path=summary_path,
        skipped_audit_path=skipped_audit_path,
        probe_manifest_path=probe_manifest_path,
        inventory_run_id="test-run-1",
    )

    records = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    skipped_records = [json.loads(line) for line in skipped_audit_path.read_text(encoding="utf-8").splitlines()]
    probe_records = [json.loads(line) for line in probe_manifest_path.read_text(encoding="utf-8").splitlines()]
    summary_data = json.loads(summary_path.read_text(encoding="utf-8"))

    assert len(records) == 3
    assert len(skipped_records) == 2
    assert len(probe_records) == 3
    assert summary.emitted_files == 3
    assert summary.skipped_files == 2
    assert summary.probe_manifest_count == 3
    pdf_record = next(record for record in records if record["name"] == "Sunshine Club Digital Resources.pdf")
    assert pdf_record["raw_metadata"]["inventory_run_id"] == "test-run-1"
    assert pdf_record["raw_metadata"]["content_class_stage"] == "initial_inventory"
    assert pdf_record["raw_metadata"]["initial_content_class"]["rule_id"] == "pdf_needs_text_probe"
    assert pdf_record["raw_metadata"]["needs_extraction_probe"] is True
    assert pdf_record["raw_metadata"]["review_required"] is True
    assert "low_confidence_content_class" in pdf_record["raw_metadata"]["risk_flags"]
    assert skipped_records[0]["inventory_run_id"] == "test-run-1"
    assert skipped_records[0]["source_mutation_allowed"] is False
    assert skipped_records[0]["audit_disposition"] == "system_or_temporary_junk"
    assert probe_records[0]["inventory_run_id"] == "test-run-1"
    assert probe_records[0]["safety_policy"]["source_mutation_allowed"] is False
    assert {record["probe_reason"] for record in probe_records} == {
        "binary_or_unknown_review",
        "content_type_probe_required",
    }
    assert output_path.name not in [record["name"] for record in records]
    assert skipped_audit_path.name not in [record["name"] for record in records]
    assert probe_manifest_path.name not in [record["name"] for record in records]
    assert summary_data["inventory_run_id"] == "test-run-1"
    assert summary_data["emitted_files"] == 3
    assert summary_data["skipped_by_reason"] == {
        "skip_directory:#recycle": 1,
        "skip_file:.ds_store": 1,
    }
    assert summary_data["by_content_class"]["binary_or_unknown"] == 1
    assert summary_data["low_confidence"]["count"] == 3
    assert summary_data["needs_extraction_probe"]["count"] == 2
    assert summary_data["probe_manifest"]["count"] == 3


def test_content_class_transition_contract_preserves_before_after_and_review_policy() -> None:
    transition = ContentClassTransition(
        source_path="/mnt/sunshine/Sunshine shared folders/Unsorted/page.jpg",
        inventory_run_id="test-run-1",
        before_class=FileContentClass.IMAGE,
        after_class=FileContentClass.SCANNED_DOCUMENT,
        transition_reason="ocr_text_detected",
        extractor_name="probe-stub",
        extraction_quality=ExtractionQuality.OK,
        warnings=[],
        requires_review=False,
    )

    assert transition.before_class == FileContentClass.IMAGE
    assert transition.after_class == FileContentClass.SCANNED_DOCUMENT
    assert transition.inventory_run_id == "test-run-1"


def test_content_class_probe_audit_summary_contract_tracks_customer_safety_counts() -> None:
    summary = ContentClassProbeAuditSummary(
        inventory_run_id="test-run-1",
        probe_run_id="probe-run-1",
        generated_at=datetime.now(UTC),
        total_probe_candidates=10,
        unchanged_classifications=4,
        changed_classifications=2,
        failed_extractions=1,
        empty_or_poor_extractions=1,
        still_unknown=1,
        review_required=3,
        skipped_files=1,
        skipped_by_reason={"skip_file:.ds_store": 1},
        by_transition={"image->scanned_document": 2},
    )

    assert summary.total_probe_candidates == 10
    assert summary.changed_classifications == 2
    assert summary.review_required == 3
