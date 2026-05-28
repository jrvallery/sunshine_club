from __future__ import annotations

import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import PdfWriter

from sunshine_extraction.config.models import ProviderConfig
from sunshine_extraction.config.provider_registry import DEFAULT_PROVIDER_REGISTRY, REQUIRED_CAPABILITIES, provider_registry_rows, validate_provider_registry
from sunshine_extraction.embeddings import EmbeddingConfigurationError, PlaceholderEmbeddingProvider, provider_from_env
from sunshine_extraction.domain.artifacts import ArtifactManifestEntry
from sunshine_extraction.domain.chunks import chunk_row
from sunshine_extraction.domain.model_usage import ModelUsageRow, cost_basis
from sunshine_extraction.domain.tags import tag_candidate_row
from sunshine_extraction.domain.taxonomy import TaxonomyOptions
from sunshine_extraction.providers.probe import NativeFileProbeProvider
from sunshine_extraction.providers.chunking import CurrentChunkingProvider, LlamaIndexChunkingProvider, StructureAwareChunkingProvider
from sunshine_extraction.providers.chunking.legacy import chunk_content as legacy_chunk_content
from sunshine_extraction.providers.embeddings import CortexEmbeddingProvider, CurrentChunkEmbeddingProvider, HostedOpenAIEmbeddingProvider, embedding_cache_key
from sunshine_extraction.providers.extraction import (
    CurrentExtractionProvider,
    DoclingExtractionProvider,
    HostedOpenAIOcrExecutor,
    MinerUExtractionProvider,
    RAGFlowDeepDocExtractionProvider,
    UnstructuredExtractionProvider,
    extraction_provider_from_env,
)
from sunshine_extraction.providers.extraction.router import select_extraction_provider
from sunshine_extraction.providers.llm import CortexLLMTagInspector, CurrentLLMTagInspectionProvider, HostedOpenAILLMTagInspector, llm_cache_key
from sunshine_extraction.providers.observability import LangfuseObservabilityProvider, NoopObservabilityProvider
from sunshine_extraction.providers.reranking import CortexRerankProvider
from sunshine_extraction.providers.retrieval import CurrentSemanticRetrievalProvider, GoldenExampleRetrievalProvider, QdrantSemanticRetrievalProvider
from sunshine_extraction.providers.vectorstores import NoopVectorStoreProvider, QdrantVectorStoreProvider, SQLiteGoldenVectorStoreProvider
from sunshine_extraction.domain.documents import IMAGE_EXTENSIONS, SPREADSHEET_EXTENSIONS, TEXT_EXTENSIONS, SampleFile
from sunshine_extraction.services.artifacts.writers import extraction_result_row, sample_input_row, write_pipeline_result
from sunshine_extraction.services.artifact_manifest import build_artifact_manifest
from sunshine_extraction.services.cache import SQLiteModelCallCache
from sunshine_extraction.services.classification.extraction_plan import provider_hints
from sunshine_extraction.services.provider_policy import assert_local_provider
from sunshine_extraction.services.confidence import calibrate_confidence, confidence_calibration_row
from sunshine_extraction.services.extraction import ocr_executor_from_env
from sunshine_extraction.services.quality import extraction_quality_gate, quality_gate_row, validate_extracted_text, validation_row, with_text_validation
from sunshine_extraction.services.routing import resolve_route_decision
from sunshine_extraction.services.segmentation import propose_document_segments
from sunshine_extraction.services.tagging.evidence import combine_tag_candidates
from sunshine_extraction.services.tagging.llm_inspection import llm_tag_inspector_from_env
from sunshine_extraction.services.tagging.rules import assign_tag_candidates
from sunshine_extraction.services.tagging.taxonomy import DEFAULT_TAXONOMY_PATH
from sunshine_extraction.services.vectorization import embed_chunks, embed_chunks_with_fallback
from sunshine_extraction.services.vector_policy import vector_store_policy_from_env
from sunshine_extraction.services.extraction import ExtractionResult
from sunshine_extraction.services.structure import normalize_document_structure


class _FakeDoclingPage:
    def __init__(self, page_no: int, text: str) -> None:
        self.page_no = page_no
        self.text = text


class _FakeDoclingDocument:
    pages = [
        _FakeDoclingPage(1, "Sunshine founders history and anniversary notes."),
        _FakeDoclingPage(2, "Newspaper article clipping from the Longmont Ledger."),
    ]
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


class _CountingEmbeddingProvider(PlaceholderEmbeddingProvider):
    provider_name = "counting"

    def __init__(self) -> None:
        super().__init__(dimensions=4)
        self.model = "counting-embedding"
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return super().embed(texts)


class _CountingLLMTagInspector(_FakeLLMTagInspector):
    def __init__(self) -> None:
        self.calls = 0

    def inspect(self, **kwargs):
        self.calls += 1
        return super().inspect(**kwargs)


def _sample(path: Path, *, relative_path: str = "Sunshine shared folders/file.pdf") -> SampleFile:
    return SampleFile(
        sample_path=path,
        source_path=f"/source/{path.name}",
        relative_path=relative_path,
        sample_group="test",
        sample_number=1,
        index_row={"metadata": {}},
    )


def test_document_domain_exports_source_file_contract() -> None:
    assert ".pdf" not in TEXT_EXTENSIONS
    assert ".jpg" in IMAGE_EXTENSIONS
    assert ".xlsx" in SPREADSHEET_EXTENSIONS


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


def test_chunking_provider_boundaries_are_local_only(tmp_path: Path) -> None:
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

    chunks, attempt = StructureAwareChunkingProvider().chunk(extraction, {"quality": "ok", "can_chunk": True})
    skipped_chunks, skipped_attempt = LlamaIndexChunkingProvider().chunk(extraction, {"quality": "ok", "can_chunk": True})

    assert chunks[0]["chunking_provider"] == "structure_aware"
    assert attempt.provider == "structure_aware"
    assert attempt.metadata["wrapped_provider"] == "current"
    assert LlamaIndexChunkingProvider().dependency_status()["local_only"] is True
    assert skipped_chunks == []
    assert skipped_attempt.status == "skipped"
    assert "llamaindex_chunking_not_enabled" in skipped_attempt.warnings


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


def test_chunk_domain_contract_writes_compatible_rows(tmp_path: Path) -> None:
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

    row = chunk_row(extraction, 2, "text", "minutes", {"char_start": 8, "char_end": 15})

    assert row == {
        "source_path": f"/source/{source.name}",
        "relative_path": "Sunshine shared folders/file.pdf",
        "sample_path": str(source),
        "chunk_id": "test:1:2",
        "chunk_index": 2,
        "chunk_kind": "text",
        "text": "minutes",
        "metadata": {"char_start": 8, "char_end": 15},
    }


def test_model_usage_domain_contract_tracks_cost_basis() -> None:
    row = ModelUsageRow(
        source_path="/source/file.pdf",
        relative_path="file.pdf",
        node="embed_chunks",
        purpose="chunk_embedding",
        provider="cortex",
        model="local-model",
        status="ok",
        runtime_ms=12,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        estimated_cost_usd=None,
        cost_basis=cost_basis("cortex"),
        error=None,
        metadata={"call_count": 1},
    ).as_row()

    assert row["cost_basis"] == "local"
    assert cost_basis("openai") == "external"
    assert cost_basis("placeholder") == "placeholder"


def test_taxonomy_and_tag_domain_contracts_are_service_compatible() -> None:
    taxonomy = TaxonomyOptions(
        primary_tags=["meeting_records"],
        secondary_tags=["minutes"],
        primary_definitions={"meeting_records": "Meeting minutes and agendas."},
    )
    candidate = tag_candidate_row(
        source_path="/source/minutes.pdf",
        relative_path="minutes.pdf",
        tag=taxonomy.primary_tags[0],
        confidence=0.91,
        evidence=["matched:minutes"],
        secondary_tags=taxonomy.secondary_tags,
        assignment_source="deterministic",
    )

    assert candidate["tag"] == "meeting_records"
    assert candidate["secondary_tags"] == ["minutes"]
    assert "requires_review" not in candidate


def test_artifact_manifest_domain_contract_preserves_optional_note(tmp_path: Path) -> None:
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    (output_dir / "sample-route-decisions.jsonl").write_text('{"route_status":"route_candidate"}\n', encoding="utf-8")

    manifest = build_artifact_manifest(output_dir, expected_names=["missing.jsonl"], run_id="run-1", generated_at="2026-05-28T00:00:00+00:00")
    manifest_by_name = {row["name"]: row for row in manifest["artifacts"]}
    standalone = ArtifactManifestEntry(
        name="artifact-manifest.json",
        path=str(output_dir / "artifact-manifest.json"),
        kind="json",
        exists=True,
        size_bytes=1,
        modified_at=None,
        row_count=None,
        sha256=None,
        note="self_referential_manifest",
    ).as_row()

    assert manifest["run_id"] == "run-1"
    assert manifest_by_name["sample-route-decisions.jsonl"]["row_count"] == 1
    assert manifest_by_name["missing.jsonl"]["exists"] is False
    assert standalone["note"] == "self_referential_manifest"


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


def test_chunk_embedding_provider_uses_sqlite_model_cache(tmp_path: Path) -> None:
    chunks = [
        {
            "source_path": "/source/minutes.txt",
            "relative_path": "Minutes/minutes.txt",
            "chunk_id": "chunk-1",
            "text": "Meeting minutes text",
        }
    ]
    embedding_provider = _CountingEmbeddingProvider()
    cache = SQLiteModelCallCache(tmp_path / "model-cache.sqlite")
    provider = CurrentChunkEmbeddingProvider(embedding_provider, cache=cache)

    first_rows, first_attempt = provider.embed_chunks(chunks, failure_mode="review")
    second_rows, second_attempt = provider.embed_chunks(chunks, failure_mode="review")

    assert embedding_provider.calls == 1
    assert first_rows[0]["embedding_status"] == "placeholder"
    assert second_rows[0]["cache_status"] == "hit"
    assert first_attempt.metadata["cache_misses"] == 1
    assert second_attempt.metadata["cache_hits"] == 1
    assert second_attempt.metadata["cache_misses"] == 0


def test_embedding_provider_modules_expose_local_only_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUNSHINE_EMBEDDING_PROVIDER", "cortex")
    monkeypatch.setenv("CORTEX_API_KEY", "local-test-key")
    monkeypatch.delenv("CORTEX_OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("CORTEX_BASE_URL", "http://cortex.local")
    monkeypatch.setenv("SUNSHINE_EMBEDDING_MODEL", "local-embedding-model")
    monkeypatch.setenv("SUNSHINE_EMBEDDING_DIMENSIONS", "17")

    provider = provider_from_env()
    cache_key = embedding_cache_key(text="hello", provider="cortex", model="local-embedding-model", dimensions=17)

    assert isinstance(provider, CortexEmbeddingProvider)
    assert provider.provider_name == "cortex"
    assert provider.base_url == "http://cortex.local/v1"
    assert len(cache_key) == 64
    with pytest.raises(EmbeddingConfigurationError):
        HostedOpenAIEmbeddingProvider()


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


def test_retrieval_and_rerank_provider_boundaries_are_local_only() -> None:
    golden = GoldenExampleRetrievalProvider(PlaceholderEmbeddingProvider(dimensions=4))
    qdrant = QdrantSemanticRetrievalProvider(url="http://127.0.0.1:6333", collection="sunshine-test")
    reranker = CortexRerankProvider(api_key="", base_url="http://cortex.local", model="rerank-local")

    qdrant_examples, qdrant_attempt = qdrant.retrieve(index_path=None, query_text="meeting", limit=3)
    reranked, rerank_attempt = reranker.rerank(query_text="meeting", documents=[{"text": "minutes"}], limit=1)

    assert golden.provider_name == "sqlite_semantic_index"
    assert qdrant.dependency_status()["local_only"] is True
    assert qdrant_examples == []
    assert qdrant_attempt.provider == "qdrant"
    assert qdrant_attempt.status == "skipped"
    assert "qdrant_embedding_provider_missing" in qdrant_attempt.warnings
    assert reranked == [{"text": "minutes"}]
    assert rerank_attempt.provider == "cortex"
    assert rerank_attempt.status == "skipped"
    assert rerank_attempt.metadata["local_only"] is True


def test_qdrant_retrieval_provider_queries_local_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakePoint:
        score = 0.87
        payload = {"source_path": "/source/minutes.pdf", "correct_primary_tag": "meeting_records", "text": "minutes"}

    class FakeClient:
        def __init__(self, *, url: str) -> None:
            captured["url"] = url

        def search(self, *, collection_name: str, query_vector: list[float], limit: int, with_payload: bool) -> list[FakePoint]:
            captured["collection_name"] = collection_name
            captured["query_vector"] = query_vector
            captured["limit"] = limit
            captured["with_payload"] = with_payload
            return [FakePoint()]

    fake_module = types.SimpleNamespace(QdrantClient=FakeClient)
    monkeypatch.setitem(sys.modules, "qdrant_client", fake_module)
    provider = QdrantSemanticRetrievalProvider(
        embedding_provider=PlaceholderEmbeddingProvider(dimensions=3),
        url="http://127.0.0.1:6333",
        collection="sunshine-test",
    )

    examples, attempt = provider.retrieve(index_path=None, query_text="meeting minutes", limit=2)

    assert attempt.status == "retrieved"
    assert attempt.query_count == 1
    assert attempt.result_count == 1
    assert captured["collection_name"] == "sunshine-test"
    assert captured["limit"] == 2
    assert len(captured["query_vector"]) == 3
    assert examples[0]["correct_primary_tag"] == "meeting_records"
    assert examples[0]["retrieval_provider"] == "qdrant"
    assert examples[0]["score"] == 0.87


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


def test_llm_tag_inspection_provider_uses_sqlite_model_cache(tmp_path: Path) -> None:
    source = tmp_path / "tea.txt"
    source.write_text("Annual tea notes", encoding="utf-8")
    sample = _sample(source)
    taxonomy = type("Taxonomy", (), {"primary_tags": ["annual_spring_tea"], "secondary_tags": [], "primary_definitions": {}})()
    inspector = _CountingLLMTagInspector()
    provider = CurrentLLMTagInspectionProvider(inspector, cache=SQLiteModelCallCache(tmp_path / "model-cache.sqlite"))
    extraction = ExtractionResult(
        sample=sample,
        plan={"strategy": "text_extraction"},
        extraction_status="extracted",
        text="Annual tea notes",
        metadata={},
        page_count=1,
        warnings=[],
    )

    first_inspection, first_attempt = provider.inspect_tags(
        sample=sample,
        corrected={"final_class": "document"},
        plan={"strategy": "text_extraction"},
        extraction=extraction,
        taxonomy=taxonomy,
        deterministic_candidates=[],
        semantic_examples=[],
    )
    second_inspection, second_attempt = provider.inspect_tags(
        sample=sample,
        corrected={"final_class": "document"},
        plan={"strategy": "text_extraction"},
        extraction=extraction,
        taxonomy=taxonomy,
        deterministic_candidates=[],
        semantic_examples=[],
    )

    assert inspector.calls == 1
    assert first_inspection["primary_tag"] == "annual_spring_tea"
    assert first_attempt.metadata.get("cache_hit") is None
    assert second_inspection["cache_status"] == "hit"
    assert second_attempt.metadata["cache_hit"] is True


def test_llm_provider_modules_expose_local_only_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUNSHINE_LLM_TAG_PROVIDER", "cortex")
    monkeypatch.setenv("CORTEX_API_KEY", "local-test-key")
    monkeypatch.delenv("CORTEX_OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("CORTEX_BASE_URL", "http://cortex.local")
    monkeypatch.setenv("CORTEX_MODEL", "gemma-local")

    inspector = llm_tag_inspector_from_env()
    cache_key = llm_cache_key(prompt="classify this", provider="cortex", model="gemma-local")

    assert isinstance(inspector, CortexLLMTagInspector)
    assert inspector.provider_name == "cortex"
    assert inspector.base_url == "http://cortex.local/v1"
    assert len(cache_key) == 64
    with pytest.raises(ValueError):
        HostedOpenAILLMTagInspector()


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
    assert structure["pages"][0]["text"] == "Sunshine founders history and anniversary notes."
    assert structure["pages"][1]["source"] == "docling"
    assert len(structure["tables"]) == 1
    assert len(structure["figures"]) == 3


def test_extraction_provider_factory_selects_current_and_docling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUNSHINE_EXTRACTION_PROVIDER", "current")
    assert isinstance(extraction_provider_from_env(), CurrentExtractionProvider)
    assert isinstance(extraction_provider_from_env("docling"), DoclingExtractionProvider)
    assert isinstance(extraction_provider_from_env("mineru"), MinerUExtractionProvider)
    assert isinstance(extraction_provider_from_env("ragflow_deepdoc"), RAGFlowDeepDocExtractionProvider)
    assert isinstance(extraction_provider_from_env("unstructured"), UnstructuredExtractionProvider)


def test_parser_provider_policy_can_promote_local_ocr_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUNSHINE_OCR_PARSER_PROVIDER", "unstructured")

    hints = provider_hints({"image_only_pdf_likelihood": 0.95}, "ocr_page_level")

    assert hints["preferred_parser"] == "unstructured"


def test_extraction_provider_router_falls_back_when_promoted_parser_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUNSHINE_OCR_PARSER_PROVIDER", "unstructured")
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"fake")

    selection = select_extraction_provider(
        _sample(source),
        {"strategy": "ocr_page_level", "provider_hints": provider_hints({"image_only_pdf_likelihood": 0.95}, "ocr_page_level")},
        {"media_type": "pdf", "image_only_pdf_likelihood": 0.95},
        CurrentExtractionProvider(),
    )

    assert selection["preferred_provider"] == "unstructured"
    assert selection["selected_provider"] == "current"
    assert selection["provider_chain"] == ["unstructured", "cortex_ocr", "current"]
    assert selection["provider_selection_reason"] == "preferred_unstructured_unavailable_fell_back_to_configured"
    assert selection["skipped_providers"][0]["provider"] == "unstructured"


def test_optional_extraction_provider_boundaries_are_local_only(tmp_path: Path) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"fake")
    sample = _sample(source)
    providers = [
        MinerUExtractionProvider(),
        RAGFlowDeepDocExtractionProvider(),
        UnstructuredExtractionProvider(),
    ]

    for provider in providers:
        extraction, attempt = provider.extract(sample, {"strategy": "ocr_page_level"})

        assert provider.dependency_status()["local_only"] is True
        assert extraction.metadata["local_only"] is True
        assert attempt.status == "skipped"
        assert attempt.metadata["local_only"] is True

    with pytest.raises(ValueError):
        HostedOpenAIOcrExecutor()


def test_qdrant_vector_provider_is_optional_and_local_only() -> None:
    status = QdrantVectorStoreProvider(url="http://127.0.0.1:6333", collection="test").dependency_status()

    assert status["provider"] == "qdrant"
    assert status["local_only"] is True
    assert "client_available" in status
    assert "server_available" in status


def test_qdrant_vector_provider_reports_collection_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCollection:
        points_count = 7
        vectors_count = 7
        config = types.SimpleNamespace(params=types.SimpleNamespace(vectors=types.SimpleNamespace(size=1024)))

    class FakeClient:
        def __init__(self, *, url: str, timeout: float) -> None:
            self.url = url
            self.timeout = timeout

        def collection_exists(self, *, collection_name: str) -> bool:
            assert collection_name == "sunshine-test"
            return True

        def get_collection(self, *, collection_name: str) -> FakeCollection:
            assert collection_name == "sunshine-test"
            return FakeCollection()

    fake_module = types.SimpleNamespace(QdrantClient=FakeClient)
    monkeypatch.setitem(sys.modules, "qdrant_client", fake_module)
    monkeypatch.setenv("SUNSHINE_EMBEDDING_DIMENSIONS", "1024")

    status = QdrantVectorStoreProvider(url="http://127.0.0.1:6333", collection="sunshine-test").dependency_status()

    assert status["available"] is True
    assert status["server_available"] is True
    assert status["collection_exists"] is True
    assert status["provisioned"] is True
    assert status["expected_vector_size"] == 1024
    assert status["collection"] == "sunshine-test"
    assert status["collection_info"]["vector_size"] == 1024
    assert status["collection_info"]["points_count"] == 7
    assert status["url"] == "http://127.0.0.1:6333"


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


def test_vector_store_policy_defaults_to_noop_for_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUNSHINE_VECTOR_STORE", raising=False)
    monkeypatch.delenv("SUNSHINE_REQUIRE_QDRANT", raising=False)
    monkeypatch.delenv("SUNSHINE_RUNTIME_MODE", raising=False)

    policy = vector_store_policy_from_env()

    assert policy["runtime_mode"] == "development"
    assert policy["provider"] == "noop"
    assert policy["qdrant_required"] is False


def test_vector_store_policy_requires_qdrant_for_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUNSHINE_RUNTIME_MODE", "production")
    monkeypatch.delenv("SUNSHINE_VECTOR_STORE", raising=False)

    policy = vector_store_policy_from_env()

    assert policy["provider"] == "qdrant"
    assert policy["qdrant_required"] is True
    assert policy["qdrant_required_reason"] == "production_mode"

    monkeypatch.setenv("SUNSHINE_VECTOR_STORE", "noop")
    with pytest.raises(ValueError, match="Qdrant is required"):
        vector_store_policy_from_env()


def test_sqlite_golden_vectorstore_and_observability_boundaries_are_local_only() -> None:
    sqlite_result = SQLiteGoldenVectorStoreProvider(index_path=".local/test.sqlite").upsert_embeddings(
        [{"chunk_id": "chunk-1"}],
        [{"chunk_id": "chunk-1", "embedding_status": "embedded"}],
    )
    langfuse_status = LangfuseObservabilityProvider(host="http://127.0.0.1:3000").dependency_status()
    noop_status = NoopObservabilityProvider().dependency_status()

    assert sqlite_result.provider == "sqlite_golden"
    assert sqlite_result.status == "skipped"
    assert sqlite_result.metadata["local_only"] is True
    assert langfuse_status["provider"] == "langfuse"
    assert langfuse_status["local_only"] is True
    assert noop_status == {"provider": "noop", "available": True, "local_only": True}
    assert DEFAULT_PROVIDER_REGISTRY["ocr.openai"].enabled is False
    assert DEFAULT_PROVIDER_REGISTRY["observability.langfuse"].name == "langfuse"


def test_provider_registry_enforces_local_only_capability_coverage() -> None:
    validation = validate_provider_registry()
    rows = provider_registry_rows()

    assert validation["ok"] is True
    assert validation["missing_capabilities"] == []
    assert REQUIRED_CAPABILITIES <= set(validation["enabled_by_capability"])
    assert all(not row["hosted"] for row in rows if row["enabled"])
    assert any(row["key"] == "retrieval.qdrant" for row in rows)
    assert any(row["key"] == "embedding.openai" and row["hosted"] and not row["enabled"] for row in rows)


def test_provider_registry_reports_enabled_hosted_provider_as_error() -> None:
    registry = {
        **DEFAULT_PROVIDER_REGISTRY,
        "llm.openai": ProviderConfig(name="openai", capability="llm", hosted=True, local_only=False),
    }

    validation = validate_provider_registry(registry)

    assert validation["ok"] is False
    assert "llm.openai: hosted provider is enabled" in validation["errors"]
    assert "llm.openai: enabled provider is not local-only" in validation["errors"]


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


def test_segmentation_proposes_mixed_collection_page_ranges_from_page_text(tmp_path: Path) -> None:
    source = tmp_path / "packet.pdf"
    source.write_text("fake", encoding="utf-8")
    sample = _sample(source, relative_path="archive/history/scan_packet.pdf")
    extraction = ExtractionResult(
        sample=sample,
        plan={"strategy": "ocr_page_level"},
        extraction_status="extracted",
        text="A mixed collection of historical pages",
        metadata={},
        page_count=4,
        warnings=[],
    )

    segments = propose_document_segments(
        extraction,
        file_id="file-2",
        ocr_pages=[
            {"page_number": 1, "text": "Founders history and anniversary notes", "text_length": 36, "word_count": 5},
            {"page_number": 2, "text": "Newspaper article headline from the Ledger", "text_length": 40, "word_count": 6},
            {"page_number": 3, "text": "Photograph caption and scrapbook clipping", "text_length": 39, "word_count": 5},
            {"page_number": 4, "text": "Plain closing notes", "text_length": 19, "word_count": 3},
        ],
    )

    assert len(segments) == 4
    assert segments[0]["segment_type"] == "mixed_collection_page"
    assert segments[0]["requires_segment_review"] is True
    assert segments[0]["metadata"]["policy"] == "page_level_review_candidates"
    assert "matched:scrapbook" not in segments[0]["segment_boundary_evidence"]
    assert "page_signal:newspaper_or_article" in segments[0]["segment_boundary_evidence"]
    assert "page_signal:scrapbook_or_photo" in segments[0]["segment_boundary_evidence"]


def test_segmentation_uses_provider_structure_pages_when_ocr_pages_are_absent(tmp_path: Path) -> None:
    source = tmp_path / "docling_packet.pdf"
    source.write_text("fake", encoding="utf-8")
    sample = _sample(source, relative_path="archive/history/docling_packet.pdf")
    extraction = ExtractionResult(
        sample=sample,
        plan={"strategy": "docling_layout"},
        extraction_status="extracted",
        text="Provider markdown for mixed historical packet",
        metadata={
            "provider": "docling",
            "docling_structure": {
                "page_count": 3,
                "pages": [
                    {
                        "page_number": 1,
                        "text": "Founders history and anniversary notes",
                        "text_length": 36,
                        "word_count": 5,
                        "provider": "docling",
                    },
                    {
                        "page_number": 2,
                        "text": "Newspaper article clipping from the Ledger",
                        "text_length": 42,
                        "word_count": 6,
                        "provider": "docling",
                    },
                    {
                        "page_number": 3,
                        "text": "Scrapbook photograph caption",
                        "text_length": 28,
                        "word_count": 3,
                        "provider": "docling",
                    },
                ],
            },
        },
        page_count=3,
        warnings=[],
    )
    structure = normalize_document_structure(extraction)

    segments = propose_document_segments(extraction, file_id="file-3", document_structure=structure)

    assert len(segments) == 3
    assert segments[0]["segment_type"] == "mixed_collection_page"
    assert segments[0]["metadata"]["policy"] == "page_level_review_candidates"
    assert "page_signal:newspaper_or_article" in segments[0]["segment_boundary_evidence"]
    assert "page_signal:scrapbook_or_photo" in segments[0]["segment_boundary_evidence"]


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
