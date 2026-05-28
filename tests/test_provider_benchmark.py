from __future__ import annotations

import json
from pathlib import Path

from sunshine_extraction.evals.provider_benchmark import benchmark_extraction_providers
from sunshine_extraction.evals.provider_benchmark_samples import generate_provider_benchmark_manifest
from sunshine_extraction.services.evaluation import benchmark_extraction_providers as benchmark_extraction_providers_service


def test_provider_benchmark_runs_current_provider_and_writes_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "minutes.txt"
    source.write_text("Meeting minutes and Sunshine Club notes.", encoding="utf-8")
    output_dir = tmp_path / "benchmark"

    result = benchmark_extraction_providers([source], provider_names=["current"], output_dir=output_dir)

    assert result["summary"]["result_count"] == 1
    assert result["summary"]["by_provider"]["current"] == 1
    assert result["summary"]["provider_availability"]["current"]["available"] is True
    assert result["summary"]["local_only"] is True
    assert result["summary"]["comparison"]["paired_file_count"] == 0
    assert result["summary"]["recommendations"][0]["provider"] == "current"
    assert result["summary"]["recommendations"][0]["promotion_status"] == "candidate"
    assert result["recommendations"][0]["ok_quality_rate"] == 1.0
    assert result["results"][0]["status"] == "extracted"
    assert result["results"][0]["quality"] == "ok"
    rows = [json.loads(line) for line in (output_dir / "provider-benchmark-results.jsonl").read_text(encoding="utf-8").splitlines()]
    parser_rows = [json.loads(line) for line in (output_dir / "sample-parser-results.jsonl").read_text(encoding="utf-8").splitlines()]
    recommendations = [json.loads(line) for line in (output_dir / "provider-benchmark-recommendations.jsonl").read_text(encoding="utf-8").splitlines()]
    summary = json.loads((output_dir / "provider-benchmark-summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "artifact-manifest.json").read_text(encoding="utf-8"))
    assert rows[0]["provider"] == "current"
    assert parser_rows[0]["parser_provider"] == "current"
    assert parser_rows[0]["status"] == "extracted"
    assert parser_rows[0]["quality"] == "ok"
    assert parser_rows[0]["text_snippet"] == "Meeting minutes and Sunshine Club notes."
    assert recommendations[0]["promotion_status"] == "candidate"
    assert summary["result_count"] == 1
    assert manifest["existing_artifact_count"] == 5
    assert {artifact["name"]: artifact["row_count"] for artifact in manifest["artifacts"] if artifact["kind"] == "jsonl"} == {
        "provider-benchmark-recommendations.jsonl": 1,
        "provider-benchmark-results.jsonl": 1,
        "sample-parser-results.jsonl": 1,
    }


def test_provider_benchmark_supports_optional_local_parser_boundaries(tmp_path: Path) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"fake pdf")

    result = benchmark_extraction_providers_service(
        [source],
        provider_names=["mineru", "ragflow_deepdoc", "unstructured"],
    )

    assert result["summary"]["result_count"] == 3
    assert result["summary"]["local_only"] is True
    assert result["summary"]["by_provider"] == {
        "mineru": 1,
        "ragflow_deepdoc": 1,
        "unstructured": 1,
    }
    assert result["summary"]["provider_availability"]["mineru"]["local_only"] is True
    assert {row["status"] for row in result["results"]} == {"skipped"}
    assert {row["promotion_status"] for row in result["recommendations"]} == {"blocked_dependency_unavailable"}


def test_provider_benchmark_loads_canonical_sample_manifest(tmp_path: Path) -> None:
    source = tmp_path / "minutes.txt"
    source.write_text("Meeting minutes and Sunshine Club notes.", encoding="utf-8")
    manifest = tmp_path / "provider-benchmark-samples.json"
    manifest.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "path": "minutes.txt",
                        "category": "born_digital_text",
                        "label": "meeting minutes text fixture",
                        "metadata": {"risk": "low"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = benchmark_extraction_providers([], provider_names=["current"], sample_manifest=manifest)

    assert result["summary"]["sample_count"] == 1
    assert result["summary"]["sample_manifest"] == str(manifest)
    assert result["summary"]["sample_categories"] == {"born_digital_text": 1}
    assert result["results"][0]["sample_category"] == "born_digital_text"
    assert result["results"][0]["sample_label"] == "meeting minutes text fixture"
    assert result["parser_results"][0]["sample_category"] == "born_digital_text"
    assert result["parser_results"][0]["metadata"]["sample_metadata"] == {"risk": "low"}


def test_provider_benchmark_filters_manifest_samples_and_writes_incremental_rows(tmp_path: Path) -> None:
    source_a = tmp_path / "minutes-a.txt"
    source_b = tmp_path / "minutes-b.txt"
    source_c = tmp_path / "scan.txt"
    for source in [source_a, source_b, source_c]:
        source.write_text(f"Sunshine content for {source.name}", encoding="utf-8")
    manifest = tmp_path / "provider-benchmark-samples.json"
    manifest.write_text(
        json.dumps(
            {
                "samples": [
                    {"path": source_a.name, "category": "born_digital_text"},
                    {"path": source_b.name, "category": "born_digital_text"},
                    {"path": source_c.name, "category": "scanned_pdf"},
                ]
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "benchmark"

    result = benchmark_extraction_providers(
        [],
        provider_names=["current"],
        output_dir=output_dir,
        sample_manifest=manifest,
        sample_categories=["born_digital_text"],
        sample_limit=1,
    )

    rows = (output_dir / "provider-benchmark-results.jsonl").read_text(encoding="utf-8").splitlines()
    parser_rows = (output_dir / "sample-parser-results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert len(parser_rows) == 1
    assert result["summary"]["sample_count"] == 1
    assert result["summary"]["sample_filter"] == {"categories": ["born_digital_text"], "limit": 1}
    assert json.loads(rows[0])["sample_path"] == str(source_a)


def test_provider_benchmark_resets_stale_complete_artifacts_before_incremental_run(tmp_path: Path) -> None:
    source = tmp_path / "minutes.txt"
    source.write_text("Meeting minutes.", encoding="utf-8")
    output_dir = tmp_path / "benchmark"
    output_dir.mkdir()
    (output_dir / "provider-benchmark-summary.json").write_text('{"stale": true}', encoding="utf-8")
    (output_dir / "provider-benchmark-recommendations.jsonl").write_text('{"provider": "stale"}\n', encoding="utf-8")

    benchmark_extraction_providers([source], provider_names=["current"], output_dir=output_dir)

    summary = json.loads((output_dir / "provider-benchmark-summary.json").read_text(encoding="utf-8"))
    recommendations = [json.loads(line) for line in (output_dir / "provider-benchmark-recommendations.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "stale" not in summary
    assert recommendations[0]["provider"] == "current"


def test_provider_benchmark_recommendations_require_runtime_review_when_too_slow(tmp_path: Path) -> None:
    class SlowProvider:
        provider_name = "slow_local"

        def dependency_status(self) -> dict[str, object]:
            return {"provider": self.provider_name, "available": True, "local_only": True}

        def extract(self, sample, plan, *, ocr_executor=None, ocr_artifacts=None):
            from sunshine_extraction.providers.extraction.base import ExtractionProviderAttempt
            from sunshine_extraction.services.extraction import ExtractionResult

            extraction = ExtractionResult(
                sample=sample,
                plan=plan,
                extraction_status="extracted",
                text="high quality but slow text",
                metadata={"provider": self.provider_name, "local_only": True},
                page_count=1,
                warnings=[],
            )
            attempt = ExtractionProviderAttempt(
                provider=self.provider_name,
                status="extracted",
                strategy=plan.get("strategy"),
                seconds=42.0,
                warnings=[],
                metadata={"local_only": True},
            )
            return extraction, attempt

    source = tmp_path / "minutes.txt"
    source.write_text("Meeting minutes.", encoding="utf-8")

    result = benchmark_extraction_providers(
        [source],
        provider_names=[],
        max_average_seconds=30.0,
        _provider_instances=[SlowProvider()],
    )

    recommendation = result["recommendations"][0]
    assert recommendation["provider"] == "slow_local"
    assert recommendation["promotion_status"] == "needs_runtime_review"
    assert recommendation["average_seconds"] == 42.0
    assert recommendation["max_average_seconds"] == 30.0


def test_provider_benchmark_scores_segmentation_readiness_for_packet_samples(tmp_path: Path) -> None:
    class PageAwareProvider:
        provider_name = "page_aware"

        def dependency_status(self) -> dict[str, object]:
            return {"provider": self.provider_name, "available": True, "local_only": True}

        def extract(self, sample, plan, *, ocr_executor=None, ocr_artifacts=None):
            from sunshine_extraction.providers.extraction.base import ExtractionProviderAttempt
            from sunshine_extraction.services.extraction import ExtractionResult

            pages = [
                {"page_number": 1, "text": "Scrapbook clipping one", "text_length": 22, "word_count": 3},
                {"page_number": 2, "text": "Scrapbook clipping two", "text_length": 22, "word_count": 3},
            ]
            extraction = ExtractionResult(
                sample=sample,
                plan=plan,
                extraction_status="extracted",
                text="Scrapbook clipping one\n\nScrapbook clipping two",
                metadata={
                    "provider": self.provider_name,
                    "local_only": True,
                    "docling_structure": {
                        "page_count": 2,
                        "pages": pages,
                        "picture_count": 2,
                        "text_item_count": 2,
                    },
                },
                page_count=2,
                warnings=[],
            )
            attempt = ExtractionProviderAttempt(
                provider=self.provider_name,
                status="extracted",
                strategy=plan.get("strategy"),
                seconds=2.0,
                warnings=[],
                metadata={"local_only": True},
            )
            return extraction, attempt

    source = tmp_path / "scrapbook.pdf"
    source.write_bytes(b"%PDF scrapbook packet")
    manifest = tmp_path / "provider-benchmark-samples.json"
    manifest.write_text(
        json.dumps({"samples": [{"path": source.name, "category": "scrapbook_packet", "label": "scrapbook packet"}]}),
        encoding="utf-8",
    )

    result = benchmark_extraction_providers(
        [],
        provider_names=[],
        sample_manifest=manifest,
        _provider_instances=[PageAwareProvider()],
    )

    parser_row = result["parser_results"][0]
    recommendation = result["recommendations"][0]
    assert parser_row["segmentation_required"] is True
    assert parser_row["segmentation_readiness"] == "ready_for_review"
    assert parser_row["page_text_coverage_rate"] == 1.0
    assert result["summary"]["segmentation"]["required_count"] == 1
    assert result["summary"]["segmentation"]["ready_for_review_count"] == 1
    assert result["summary"]["segmentation"]["by_provider"]["page_aware"]["ready_for_review_rate"] == 1.0
    assert recommendation["segmentation_required_count"] == 1
    assert recommendation["segmentation_ready_for_review_rate"] == 1.0
    assert recommendation["promotion_status"] == "candidate"


def test_provider_benchmark_blocks_promotion_when_packet_lacks_page_structure(tmp_path: Path) -> None:
    class FlatPacketProvider:
        provider_name = "flat_packet"

        def dependency_status(self) -> dict[str, object]:
            return {"provider": self.provider_name, "available": True, "local_only": True}

        def extract(self, sample, plan, *, ocr_executor=None, ocr_artifacts=None):
            from sunshine_extraction.providers.extraction.base import ExtractionProviderAttempt
            from sunshine_extraction.services.extraction import ExtractionResult

            extraction = ExtractionResult(
                sample=sample,
                plan=plan,
                extraction_status="extracted",
                text="Flat text for a multi-page newspaper packet with no page structure",
                metadata={"provider": self.provider_name, "local_only": True},
                page_count=3,
                warnings=[],
            )
            attempt = ExtractionProviderAttempt(
                provider=self.provider_name,
                status="extracted",
                strategy=plan.get("strategy"),
                seconds=1.0,
                warnings=[],
                metadata={"local_only": True},
            )
            return extraction, attempt

    source = tmp_path / "newspaper.pdf"
    source.write_bytes(b"%PDF newspaper packet")
    manifest = tmp_path / "provider-benchmark-samples.json"
    manifest.write_text(
        json.dumps({"samples": [{"path": source.name, "category": "newspaper_packet", "label": "newspaper packet"}]}),
        encoding="utf-8",
    )

    result = benchmark_extraction_providers(
        [],
        provider_names=[],
        sample_manifest=manifest,
        _provider_instances=[FlatPacketProvider()],
    )

    assert result["parser_results"][0]["segmentation_readiness"] == "missing_page_structure"
    assert result["recommendations"][0]["promotion_status"] == "needs_segmentation_review"
    assert result["recommendations"][0]["promotion_reason"] == "segmentation-required samples did not all return page-level structure ready for boundary review"


def test_provider_benchmark_records_provider_exceptions_and_continues(tmp_path: Path) -> None:
    class ExplodingProvider:
        provider_name = "exploding_local"

        def dependency_status(self) -> dict[str, object]:
            return {"provider": self.provider_name, "available": True, "local_only": True}

        def extract(self, sample, plan, *, ocr_executor=None, ocr_artifacts=None):
            raise RuntimeError("parser crashed")

    source = tmp_path / "minutes.txt"
    source.write_text("Meeting minutes and Sunshine Club notes.", encoding="utf-8")
    output_dir = tmp_path / "benchmark"

    result = benchmark_extraction_providers(
        [source],
        provider_names=[],
        output_dir=output_dir,
        _provider_instances=[ExplodingProvider()],
    )

    assert result["summary"]["result_count"] == 1
    assert result["results"][0]["provider"] == "exploding_local"
    assert result["results"][0]["status"] == "failed"
    assert result["results"][0]["requires_review"] is True
    assert result["results"][0]["warnings"] == ["provider_exception:RuntimeError"]
    assert result["parser_results"][0]["review_reason"] == "provider_exception"
    assert result["recommendations"][0]["promotion_status"] == "needs_review"
    rows = [json.loads(line) for line in (output_dir / "provider-benchmark-results.jsonl").read_text(encoding="utf-8").splitlines()]
    parser_rows = [json.loads(line) for line in (output_dir / "sample-parser-results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["metadata"]["error"] == "parser crashed"
    assert parser_rows[0]["provider_attempt"]["metadata"]["error_type"] == "RuntimeError"


def test_generate_provider_benchmark_manifest_from_qa_indexes(tmp_path: Path) -> None:
    qa_root = tmp_path / "qa samples"
    document_group = qa_root / "changed-scanned_document-to-document-pdf_extractable_text_detected"
    scanned_group = qa_root / "changed-document-to-scanned_document-pdf_image_only_or_empty_text"
    image_group = qa_root / "accepted-scanned-document-random-100"
    finance_group = qa_root / "finance"
    for group in [document_group, scanned_group, image_group, finance_group]:
        group.mkdir(parents=True)
    born = document_group / "001 - minutes.pdf"
    scanned = scanned_group / "002 - scrapbook packet.pdf"
    image = image_group / "003 - Longmont Ledger clipping.jpg"
    finance = finance_group / "004 - budget report.pdf"
    for path in [born, scanned, image, finance]:
        path.write_text("fixture", encoding="utf-8")
    _write_index(
        document_group / "index.jsonl",
        [
            {
                "after_class": "document",
                "before_class": "scanned_document",
                "link_name": born.name,
                "relative_path": "Minutes/1992-1993.pdf",
                "source_path": str(born),
                "transition_reason": "pdf_extractable_text_detected",
                "metadata": {"page_count": 12, "sample_text_chars": 1000},
            }
        ],
    )
    _write_index(
        scanned_group / "index.jsonl",
        [
            {
                "after_class": "scanned_document",
                "before_class": "document",
                "link_name": scanned.name,
                "relative_path": "History/Green scrapbook packet.pdf",
                "source_path": str(scanned),
                "transition_reason": "pdf_image_only_or_empty_text",
                "metadata": {"page_count": 30, "sample_text_chars": 0},
            }
        ],
    )
    _write_index(
        image_group / "index.jsonl",
        [
            {
                "after_class": "scanned_document",
                "before_class": "image",
                "link_name": image.name,
                "relative_path": "Press/Longmont Ledger clipping.jpg",
                "source_path": str(image),
                "transition_reason": "image_scan_evidence_confirmed",
                "metadata": {},
            }
        ],
    )
    _write_index(
        finance_group / "index.jsonl",
        [
            {
                "after_class": "document",
                "before_class": "document",
                "link_name": finance.name,
                "relative_path": "Treasurer/Budget financial report.pdf",
                "source_path": str(finance),
                "transition_reason": "pdf_extractable_text_detected",
                "metadata": {"page_count": 5, "sample_text_chars": 500},
            }
        ],
    )
    output = tmp_path / ".local" / "provider-benchmark-canonical-samples.json"

    result = generate_provider_benchmark_manifest(qa_root, output, per_category=1)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert result["sample_count"] >= 6
    assert result["missing_categories"] == []
    assert set(result["categories"]) == {
        "born_digital_text",
        "financial_table",
        "image_scan",
        "newspaper_packet",
        "scanned_pdf",
        "scrapbook_packet",
    }
    assert payload["source_qa_root"] == str(qa_root)
    assert all(Path(sample["path"]).exists() for sample in payload["samples"])


def _write_index(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
