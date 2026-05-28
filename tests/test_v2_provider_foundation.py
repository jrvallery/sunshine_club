from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import PdfWriter

from sunshine_extraction.embeddings import PlaceholderEmbeddingProvider
from sunshine_extraction.providers.probe import NativeFileProbeProvider
from sunshine_extraction.providers.chunking import CurrentChunkingProvider
from sunshine_extraction.providers.chunking.legacy import chunk_content as legacy_chunk_content
from sunshine_extraction.providers.embeddings import CurrentChunkEmbeddingProvider
from sunshine_extraction.providers.extraction import CurrentExtractionProvider, DoclingExtractionProvider, extraction_provider_from_env
from sunshine_extraction.providers.llm import CurrentLLMTagInspectionProvider
from sunshine_extraction.providers.retrieval import CurrentSemanticRetrievalProvider
from sunshine_extraction.providers.vectorstores import NoopVectorStoreProvider, QdrantVectorStoreProvider
from sunshine_extraction.sample_pipeline import SampleFile, llm_tag_inspector_from_env, ocr_executor_from_env
from sunshine_extraction.services.artifacts.writers import extraction_result_row, sample_input_row, write_pipeline_result
from sunshine_extraction.services.provider_policy import assert_local_provider
from sunshine_extraction.services.confidence import calibrate_confidence, confidence_calibration_row
from sunshine_extraction.services.quality import extraction_quality_gate, quality_gate_row, validate_extracted_text, validation_row, with_text_validation
from sunshine_extraction.services.routing import resolve_route_decision
from sunshine_extraction.services.segmentation import propose_document_segments
from sunshine_extraction.services.tagging.evidence import combine_tag_candidates
from sunshine_extraction.services.tagging.rules import assign_tag_candidates
from sunshine_extraction.services.tagging.taxonomy import DEFAULT_TAXONOMY_PATH
from sunshine_extraction.services.vectorization import embed_chunks, embed_chunks_with_fallback
from sunshine_extraction.services.extraction import ExtractionResult
from sunshine_extraction.services.structure import normalize_document_structure


class _FakeDoclingDocument:
    pages = [object(), object()]
    tables = [object()]
    pictures = [object(), object(), object()]
    groups = []
    texts = [object(), object()]

    def export_to_markdown(self) -> str:
        return "# Sunshine Docling Text\n\nMeeting minutes."


class _FakeDoclingResult:
    document = _FakeDoclingDocument()


class _FakeDoclingConverter:
    def convert(self, path: str) -> _FakeDoclingResult:
        assert path
        return _FakeDoclingResult()


class _FakeLLMTagInspector:
    model = "test-model"
    provider_name = "test"

    def inspect(self, **_kwargs):
        return {
            "llm_status": "inspected",
            "provider": "test",
            "model": self.model,
            "primary_tag": "annual_spring_tea",
            "secondary_tags": [],
            "confidence": 0.9,
            "evidence": ["tea evidence"],
            "rationale": "Strong tea evidence.",
            "needs_review": False,
            "warning": None,
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        }


def _sample(path: Path, *, relative_path: str = "Sunshine shared folders/file.pdf") -> SampleFile:
    return SampleFile(
        sample_path=path,
        source_path=f"/source/{path.name}",
        relative_path=relative_path,
        sample_group="test",
        sample_number=1,
        index_row={"metadata": {}},
    )


def test_current_extraction_provider_wraps_existing_behavior(tmp_path: Path) -> None:
    source = tmp_path / "minutes.txt"
    source.write_text("Meeting minutes text", encoding="utf-8")

    extraction, attempt = CurrentExtractionProvider().extract(_sample(source), {"strategy": "text_extraction"})

    assert extraction.extraction_status == "extracted"
    assert extraction.text == "Meeting minutes text"
    assert attempt.provider == "current"
    assert attempt.metadata["local_only"] is True


def test_current_chunking_provider_wraps_existing_behavior(tmp_path: Path) -> None:
    source = tmp_path / "minutes.txt"
    source.write_text("Meeting minutes text", encoding="utf-8")
    extraction = ExtractionResult(
        sample=_sample(source),
        plan={"strategy": "text_extraction"},
        extraction_status="extracted",
        text="Meeting minutes text",
        metadata={},
        page_count=1,
        warnings=[],
    )

    chunks, attempt = CurrentChunkingProvider().chunk(
        extraction,
        {"quality": "ok", "can_chunk": True},
    )

    assert len(chunks) == 1
    assert chunks[0]["chunking_provider"] == "current"
    assert chunks[0]["chunking_strategy"] == "fixed_size_text"
    assert attempt.provider == "current"
    assert attempt.status == "chunked"
    assert attempt.metadata["local_only"] is True


def test_legacy_chunker_preserves_metadata_fallback(tmp_path: Path) -> None:
    source = tmp_path / "scan.jpg"
    source.write_bytes(b"fake")
    extraction = ExtractionResult(
        sample=_sample(source),
        plan={"strategy": "ocr_page_level"},
        extraction_status="deferred_extractor",
        text="",
        metadata={"reason": "ocr_executor_not_installed"},
        page_count=1,
        warnings=[],
    )

    chunks = legacy_chunk_content(extraction, {"can_chunk": True})

    assert chunks[0]["chunk_kind"] == "metadata"
    assert chunks[0]["chunk_id"] == "test:1:1"
    assert "OCR deferred" in chunks[0]["text"]


def test_current_chunk_embedding_provider_wraps_existing_behavior() -> None:
    chunks = [
        {
            "source_path": "/source/minutes.txt",
            "relative_path": "Minutes/minutes.txt",
            "chunk_id": "chunk-1",
            "text": "Meeting minutes text",
        }
    ]

    rows, attempt = CurrentChunkEmbeddingProvider(PlaceholderEmbeddingProvider(dimensions=4)).embed_chunks(
        chunks,
        failure_mode="fallback",
    )

    assert rows[0]["chunk_id"] == "chunk-1"
    assert rows[0]["embedding_status"] == "placeholder"
    assert attempt.provider == "local"
    assert attempt.status == "placeholder"
    assert attempt.requested_count == 1
    assert attempt.embedded_count == 1
    assert attempt.semantic_quality is False


def test_vectorization_service_writes_compatible_embedding_rows() -> None:
    chunks = [
        {
            "source_path": "/source/minutes.txt",
            "relative_path": "Minutes/minutes.txt",
            "chunk_id": "chunk-1",
            "text": "Meeting minutes text",
        }
    ]

    rows = embed_chunks(chunks, PlaceholderEmbeddingProvider(dimensions=4))
    fallback_rows, warnings = embed_chunks_with_fallback(chunks, PlaceholderEmbeddingProvider(dimensions=4))

    assert rows[0]["chunk_id"] == "chunk-1"
    assert rows[0]["embedding_status"] == "placeholder"
    assert rows[0]["embedding_dimensions"] == 4
    assert fallback_rows[0]["chunk_id"] == "chunk-1"
    assert warnings == []


def test_current_semantic_retrieval_provider_reports_missing_index() -> None:
    examples, attempt = CurrentSemanticRetrievalProvider(PlaceholderEmbeddingProvider(dimensions=4)).retrieve(
        index_path=None,
        query_text="meeting minutes",
        limit=5,
    )

    assert examples == []
    assert attempt.provider == "sqlite_semantic_index"
    assert attempt.status == "skipped"
    assert attempt.query_count == 0
    assert attempt.result_count == 0
    assert attempt.warnings == ["semantic_index_missing"]
    assert attempt.metadata["local_only"] is True


def test_current_llm_tag_inspection_provider_wraps_existing_behavior(tmp_path: Path) -> None:
    source = tmp_path / "tea.txt"
    source.write_text("Annual tea notes", encoding="utf-8")
    sample = _sample(source)
    taxonomy = type("Taxonomy", (), {"primary_tags": ["annual_spring_tea"], "secondary_tags": [], "primary_definitions": {}})()

    inspection, attempt = CurrentLLMTagInspectionProvider(_FakeLLMTagInspector()).inspect_tags(
        sample=sample,
        corrected={"final_class": "document"},
        plan={"strategy": "text_extraction"},
        extraction=ExtractionResult(
            sample=sample,
            plan={"strategy": "text_extraction"},
            extraction_status="extracted",
            text="Annual tea notes",
            metadata={},
            page_count=1,
            warnings=[],
        ),
        taxonomy=taxonomy,
        deterministic_candidates=[],
        semantic_examples=[],
    )

    assert inspection["primary_tag"] == "annual_spring_tea"
    assert attempt.provider == "test"
    assert attempt.model == "test-model"
    assert attempt.status == "inspected"
    assert attempt.input_tokens == 10
    assert attempt.total_tokens == 15


def test_confidence_calibration_service_writes_auditable_row() -> None:
    candidates, calibration = calibrate_confidence(
        [
            {
                "tag": "annual_spring_tea",
                "confidence": 0.9,
                "evidence": ["tea evidence"],
                "secondary_tags": [],
                "assignment_source": "deterministic",
            }
        ],
        {"quality": "ok", "requires_review": False},
        {"strategy": "text_extraction"},
        llm_inspection={"llm_status": "skipped"},
        semantic_examples=[],
        embeddings=[],
    )

    row = confidence_calibration_row(
        calibration,
        source_path="/source/tea.pdf",
        relative_path="Teas/tea.pdf",
        top_candidate=candidates[0],
        quality={"quality": "ok"},
        plan={"strategy": "text_extraction"},
        candidate_count=len(candidates),
    )

    assert row["status"] == "calibrated"
    assert row["top_tag"] == "annual_spring_tea"
    assert row["calibrated_confidence"] == candidates[0]["confidence"]
    assert row["candidate_count"] == 1
    assert row["extraction_strategy"] == "text_extraction"


def test_route_decision_service_prioritizes_embedding_unavailable(tmp_path: Path) -> None:
    source = tmp_path / "tea.txt"
    source.write_text("Annual tea notes", encoding="utf-8")
    sample = _sample(source)

    route, decision = resolve_route_decision(
        sample=sample,
        tag_candidates=[{"tag": "annual_spring_tea", "confidence": 0.96}],
        extraction_quality={"quality": "ok"},
        extraction_plan={"strategy": "text_extraction"},
        warnings=["embedding_quality_unavailable"],
    )

    assert route["route_status"] == "review_embedding_unavailable"
    assert decision["accepted"] is False
    assert decision["priority"] == "high"
    assert decision["review_stage"] == "needs_ocr_review"
    assert "warning:embedding_quality_unavailable" in decision["evidence"]


def test_tagging_package_exposes_v2_boundaries() -> None:
    assert callable(assign_tag_candidates)
    assert callable(combine_tag_candidates)
    assert str(DEFAULT_TAXONOMY_PATH).endswith(".json")


def test_quality_services_write_validation_and_gate_rows(tmp_path: Path) -> None:
    source = tmp_path / "minutes.txt"
    source.write_text("Meeting minutes text", encoding="utf-8")
    sample = _sample(source)
    extraction = ExtractionResult(
        sample=sample,
        plan={"strategy": "text_extraction"},
        extraction_status="extracted",
        text="Meeting minutes text",
        metadata={},
        page_count=1,
        warnings=[],
    )

    validation = validate_extracted_text(extraction)
    validation_artifact = validation_row(sample, extraction, validation)
    extraction_with_validation = with_text_validation(extraction, validation)
    quality = extraction_quality_gate(extraction_with_validation)
    quality_artifact = quality_gate_row(
        sample,
        extraction_with_validation,
        quality,
        extraction_provider_selection={"selected_provider": "current"},
        extraction_validation=validation_artifact,
        extraction_repair={"status": "not_needed"},
    )

    assert validation_artifact["status"] == "ok"
    assert extraction_with_validation.metadata["text_validation"]["status"] == "ok"
    assert quality_artifact["quality"] == "ok"
    assert quality_artifact["provider"] == "current"
    assert "validation:ok" in quality_artifact["quality_evidence"]


def test_artifact_writers_package_preserves_pipeline_rows(tmp_path: Path) -> None:
    source = tmp_path / "1992 minutes.txt"
    source.write_text("1992 Sunshine Club meeting minutes.", encoding="utf-8")
    sample = _sample(source, relative_path="Minutes/1992 minutes.txt")
    extraction = ExtractionResult(
        sample=sample,
        plan={"strategy": "text_extraction", "document_subtype": "text_document"},
        extraction_status="extracted",
        text="1992 Sunshine Club meeting minutes.",
        metadata={},
        page_count=None,
        warnings=[],
    )

    input_row = sample_input_row(sample, {"final_class": "document", "final_status": "accepted"}, extraction.plan)
    result_row = extraction_result_row(extraction, {"quality": "ok"})
    pipeline_row = write_pipeline_result(
        sample,
        {"final_class": "document"},
        extraction.plan,
        extraction,
        {"quality": "ok"},
        chunks=[],
        embeddings=[],
        tag_candidates=[{"tag": "meeting_records", "confidence": 0.61, "evidence": ["minutes"], "secondary_tags": []}],
        route={"route_status": "review_low_confidence_tag", "review_reason": "tag_confidence_below_threshold"},
        llm_inspection={"llm_status": "skipped"},
    )

    assert input_row["final_class"] == "document"
    assert result_row["text"] == "1992 Sunshine Club meeting minutes."
    assert pipeline_row["placement_status"] == "needs_review"
    assert pipeline_row["placement"]["blocked_destination_path"] == "01_Governance_Admin/1992"


def test_docling_provider_is_optional_and_local_only() -> None:
    status = DoclingExtractionProvider().dependency_status()

    assert status["provider"] == "docling"
    assert status["local_only"] is True
    assert "available" in status


def test_docling_provider_extracts_with_injected_local_converter(tmp_path: Path) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"fake pdf")
    sample = _sample(source)
    provider = DoclingExtractionProvider(converter=_FakeDoclingConverter())

    extraction, attempt = provider.extract(sample, {"strategy": "text_extraction"})
    structure = normalize_document_structure(extraction, provider_attempts=[attempt.as_row()])

    assert extraction.extraction_status == "extracted"
    assert extraction.page_count == 2
    assert extraction.metadata["docling_structure"]["table_count"] == 1
    assert attempt.metadata["structure"]["picture_count"] == 3
    assert structure["provider"] == "docling"
    assert structure["page_count"] == 2
    assert len(structure["tables"]) == 1
    assert len(structure["figures"]) == 3


def test_extraction_provider_factory_selects_current_and_docling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUNSHINE_EXTRACTION_PROVIDER", "current")
    assert isinstance(extraction_provider_from_env(), CurrentExtractionProvider)
    assert isinstance(extraction_provider_from_env("docling"), DoclingExtractionProvider)


def test_qdrant_vector_provider_is_optional_and_local_only() -> None:
    status = QdrantVectorStoreProvider(url="http://127.0.0.1:6333", collection="test").dependency_status()

    assert status["provider"] == "qdrant"
    assert status["local_only"] is True
    assert status["url"] == "http://127.0.0.1:6333"
    assert status["collection"] == "test"


def test_noop_vector_provider_records_unconfigured_indexing() -> None:
    result = NoopVectorStoreProvider().upsert_embeddings(
        [{"chunk_id": "chunk-1", "text": "hello"}],
        [{"chunk_id": "chunk-1", "embedding_status": "embedded", "embedding": [0.1]}],
    )

    assert result.status == "skipped"
    assert result.indexed_count == 0
    assert result.skipped_count == 1
    assert result.indexed_chunk_ids == []
    assert result.skipped_chunk_ids == ["chunk-1"]
    assert "vector_store_not_configured" in result.warnings


def test_native_probe_detects_image_only_pdf_likelihood(tmp_path: Path) -> None:
    source = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with source.open("wb") as handle:
        writer.write(handle)

    probe = NativeFileProbeProvider().probe(_sample(source))

    assert probe["status"] == "probed"
    assert probe["media_type"] == "pdf"
    assert probe["page_count"] == 1
    assert probe["embedded_text_chars"] == 0
    assert probe["image_only_pdf_likelihood"] == 0.95
    assert probe["metadata"]["local_only"] is True


def test_hosted_provider_policy_blocks_openai() -> None:
    with pytest.raises(ValueError):
        assert_local_provider("openai", purpose="ocr")


def test_env_provider_selection_does_not_return_hosted_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUNSHINE_LLM_TAG_PROVIDER", "openai")
    monkeypatch.setenv("SUNSHINE_OCR_FALLBACK_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-be-used")

    assert llm_tag_inspector_from_env().__class__.__name__ == "LLMTagInspector"
    assert ocr_executor_from_env().__class__.__name__ == "LocalTesseractOcrExecutor"


def test_segmentation_marks_long_scrapbook_pdf_for_segment_review(tmp_path: Path) -> None:
    source = tmp_path / "scrapbook.pdf"
    source.write_text("fake", encoding="utf-8")
    sample = _sample(source, relative_path="Sunshine shared folders/Scrapbooks/Green scrapbook.pdf")
    extraction = ExtractionResult(
        sample=sample,
        plan={"strategy": "ocr_page_level", "document_subtype": "scrapbook"},
        extraction_status="extracted",
        text="Scrapbook page text",
        metadata={},
        page_count=12,
        warnings=[],
    )

    segments = propose_document_segments(extraction, file_id="file-1")

    assert len(segments) == 12
    assert segments[0]["parent_file_id"] == "file-1"
    assert segments[0]["segment_id"] == "file-1:pages-00001-00001:segment-001"
    assert segments[-1]["segment_id"] == "file-1:pages-00012-00012:segment-012"
    assert segments[0]["segment_type"] == "scrapbook_page"
    assert segments[0]["page_start"] == 1
    assert segments[0]["page_end"] == 1
    assert segments[0]["requires_segment_review"] is True
    assert segments[0]["metadata"]["policy"] == "page_level_review_candidates"


def test_segmentation_uses_blank_pages_as_review_boundaries(tmp_path: Path) -> None:
    source = tmp_path / "scrapbook.pdf"
    source.write_text("fake", encoding="utf-8")
    sample = _sample(source, relative_path="Sunshine shared folders/Scrapbooks/Green scrapbook.pdf")
    extraction = ExtractionResult(
        sample=sample,
        plan={"strategy": "ocr_page_level", "document_subtype": "scrapbook"},
        extraction_status="extracted",
        text="First clipping\nSecond clipping",
        metadata={},
        page_count=5,
        warnings=[],
    )

    segments = propose_document_segments(
        extraction,
        file_id="file-1",
        ocr_pages=[
            {"page_number": 1, "text": "First clipping", "text_length": 14, "word_count": 2},
            {"page_number": 2, "text": "", "text_length": 0, "word_count": 0, "warnings": ["ocr_page_text_empty"]},
            {"page_number": 3, "text": "Second clipping", "text_length": 15, "word_count": 2},
            {"page_number": 4, "text": "continued", "text_length": 9, "word_count": 1},
            {"page_number": 5, "text": "", "text_length": 0, "word_count": 0},
        ],
    )

    assert [(segment["page_start"], segment["page_end"]) for segment in segments] == [(1, 1), (3, 4)]
    assert [segment["segment_id"] for segment in segments] == [
        "file-1:pages-00001-00001:segment-001",
        "file-1:pages-00003-00004:segment-002",
    ]
    assert all(segment["requires_segment_review"] for segment in segments)
    assert segments[1]["segment_type"] == "scrapbook_page_group"
    assert segments[1]["metadata"]["policy"] == "separator_page_groups"


def test_segmentation_ids_are_stable_without_qa_sample_number(tmp_path: Path) -> None:
    source = tmp_path / "scrapbook.pdf"
    source.write_text("fake", encoding="utf-8")
    sample = _sample(source, relative_path="Sunshine shared folders/Scrapbooks/Green scrapbook.pdf")
    extraction = ExtractionResult(
        sample=sample,
        plan={"strategy": "ocr_page_level", "document_subtype": "scrapbook"},
        extraction_status="extracted",
        text="Scrapbook page text",
        metadata={},
        page_count=2,
        warnings=[],
    )

    first_segments = propose_document_segments(extraction)
    changed_extraction = replace(extraction, sample=replace(sample, sample_number=99))
    second_segments = propose_document_segments(changed_extraction)

    assert [segment["segment_id"] for segment in first_segments] == [segment["segment_id"] for segment in second_segments]
    assert first_segments[0]["segment_id"].startswith("source-")
