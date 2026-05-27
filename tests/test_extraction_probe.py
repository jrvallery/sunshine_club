from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from sunshine_extraction.probe import probe_manifest_row, run_probe_manifest


def _manifest_row(path: Path, root: Path, *, content_class: str, reasons: list[str] | None = None) -> dict:
    return {
        "inventory_run_id": "inventory-test",
        "source_path": str(path),
        "relative_path": str(path.relative_to(root)),
        "source_collection": "sunshine_shared_folders",
        "name": path.name,
        "extension": path.suffix.lower().lstrip(".") or None,
        "mime_type": "application/octet-stream",
        "size_bytes": path.stat().st_size,
        "source_mtime": "2026-05-25T00:00:00+00:00",
        "content_class": content_class,
        "confidence": 0.58,
        "reasons": reasons or [],
        "risk_flags": ["low_confidence_content_class"],
        "probe_reason": "content_type_probe_required",
        "safety_policy": {
            "source_mutation_allowed": False,
            "failed_probe_disposition": "requires_review",
            "empty_probe_disposition": "requires_review",
        },
    }


def _write_text_pdf(path: Path) -> None:
    path.write_bytes(
        b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 188 >>
stream
BT /F1 12 Tf 72 720 Td (This Sunshine Club document has enough extractable text to be treated as born digital. This Sunshine Club document has enough extractable text to be treated as born digital.) Tj ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000241 00000 n 
0000000480 00000 n 
trailer
<< /Root 1 0 R /Size 6 >>
startxref
550
%%EOF
"""
    )


def test_pdf_probe_detects_extractable_text(tmp_path: Path) -> None:
    path = tmp_path / "Sunshine shared folders" / "Admin Docs" / "policy.pdf"
    path.parent.mkdir(parents=True)
    _write_text_pdf(path)

    result = probe_manifest_row(
        _manifest_row(path, tmp_path, content_class="document", reasons=["pdf_needs_text_probe"]),
        "probe-test",
    )

    assert result.status == "probed"
    assert result.after_class == "document"
    assert result.transition_reason == "pdf_extractable_text_detected"
    assert result.requires_review is False
    assert result.transition.before_class == "document"
    assert result.transition.after_class == "document"


def test_image_probe_accepts_generic_readable_image_by_policy(tmp_path: Path) -> None:
    path = tmp_path / "Sunshine shared folders" / "Unsorted" / "unknown.jpg"
    path.parent.mkdir(parents=True)
    Image.new("RGB", (1200, 900), color="white").save(path)

    result = probe_manifest_row(
        _manifest_row(path, tmp_path, content_class="image", reasons=["image_extension_needs_probe"]),
        "probe-test",
    )

    assert result.status == "probed"
    assert result.after_class == "image"
    assert result.requires_review is False
    assert result.review_reasons == []
    assert result.transition_reason == "generic_readable_image_accepted_by_policy"
    assert result.metadata["ocr_eligible"] is True


def test_image_probe_uses_path_policy_for_scanned_page_images(tmp_path: Path) -> None:
    path = tmp_path / "Sunshine shared folders" / "Scholarship" / "Sunshine_docs_0008_a.jpg"
    path.parent.mkdir(parents=True)
    Image.new("RGB", (1200, 900), color="white").save(path)

    result = probe_manifest_row(
        _manifest_row(path, tmp_path, content_class="image", reasons=["image_extension_needs_probe"]),
        "probe-test",
    )

    assert result.status == "probed"
    assert result.after_class == "scanned_document"
    assert result.transition_reason == "image_scan_policy_path_or_name"
    assert result.requires_review is False


def test_tiff_probe_confirms_readable_scanned_document(tmp_path: Path) -> None:
    path = tmp_path / "Sunshine shared folders" / "Records" / "page.tif"
    path.parent.mkdir(parents=True)
    Image.new("RGB", (1200, 1600), color="white").save(path)

    result = probe_manifest_row(
        _manifest_row(path, tmp_path, content_class="scanned_document", reasons=["tiff_scan_default"]),
        "probe-test",
    )

    assert result.status == "probed"
    assert result.after_class == "scanned_document"
    assert result.transition_reason == "tiff_readable_document_image"
    assert result.requires_review is False


def test_unknown_binary_probe_assigns_review_bucket(tmp_path: Path) -> None:
    path = tmp_path / "Sunshine shared folders" / "Teas" / "handout.pub"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"publisher")

    result = probe_manifest_row(
        _manifest_row(path, tmp_path, content_class="binary_or_unknown", reasons=["no_deterministic_rule"]),
        "probe-test",
    )

    assert result.status == "probed"
    assert result.after_class == "binary_or_unknown"
    assert result.transition_reason == "publisher_file_review"
    assert result.requires_review is True


def test_probe_accepts_large_image_with_policy_instead_of_human_review(tmp_path: Path) -> None:
    path = tmp_path / "Sunshine shared folders" / "Large" / "photo.jpg"
    path.parent.mkdir(parents=True)
    Image.new("RGB", (1200, 900), color="white").save(path)

    result = probe_manifest_row(
        _manifest_row(path, tmp_path, content_class="image", reasons=["image_extension_needs_probe"]),
        "probe-test",
        max_image_bytes=1,
    )

    assert result.status == "probed"
    assert result.after_class == "image"
    assert result.transition_reason == "generic_readable_image_accepted_by_policy_large_file"
    assert result.requires_review is False
    assert result.metadata["lightweight_probe_skipped"] is True


def test_probe_classifies_large_scan_like_image_without_human_review(tmp_path: Path) -> None:
    path = tmp_path / "Sunshine shared folders" / "Large" / "scan.jpg"
    path.parent.mkdir(parents=True)
    Image.new("RGB", (1200, 900), color="white").save(path)

    result = probe_manifest_row(
        _manifest_row(path, tmp_path, content_class="image", reasons=["image_extension_needs_probe"]),
        "probe-test",
        max_image_bytes=1,
    )

    assert result.status == "probed"
    assert result.after_class == "scanned_document"
    assert result.transition_reason == "image_scan_policy_path_or_name_large_file"
    assert result.requires_review is False


def test_run_probe_manifest_writes_one_result_per_manifest_row_and_summary(tmp_path: Path) -> None:
    pdf_path = tmp_path / "Sunshine shared folders" / "Admin Docs" / "policy.pdf"
    jpg_path = tmp_path / "Sunshine shared folders" / "Unsorted" / "unknown.jpg"
    pdf_path.parent.mkdir(parents=True)
    jpg_path.parent.mkdir(parents=True)
    _write_text_pdf(pdf_path)
    Image.new("RGB", (1200, 900), color="white").save(jpg_path)
    manifest_path = tmp_path / "_manifest" / "probe-manifest.jsonl"
    results_path = tmp_path / "_manifest" / "probe-results.jsonl"
    summary_path = tmp_path / "_manifest" / "probe-summary.json"
    manifest_path.parent.mkdir(parents=True)
    rows = [
        _manifest_row(pdf_path, tmp_path, content_class="document", reasons=["pdf_needs_text_probe"]),
        _manifest_row(jpg_path, tmp_path, content_class="image", reasons=["image_extension_needs_probe"]),
    ]
    manifest_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    summary = run_probe_manifest(
        manifest_path,
        results_path=results_path,
        summary_path=summary_path,
        probe_run_id="probe-test",
    )

    result_rows = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines()]
    summary_data = json.loads(summary_path.read_text(encoding="utf-8"))

    assert len(result_rows) == 2
    assert summary.total_probe_candidates == 2
    assert summary.review_required == 0
    assert summary_data["total_probe_candidates"] == 2
    assert summary_data["unchanged_classifications"] == 2
