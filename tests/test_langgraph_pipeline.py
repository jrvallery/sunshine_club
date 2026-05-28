from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pypdf import PdfWriter

from sunshine_extraction.embeddings import EmbeddingProviderError, PlaceholderEmbeddingProvider
from sunshine_extraction.providers.extraction import CurrentExtractionProvider, ExtractionProviderAttempt
from sunshine_extraction.providers.reranking.base import RerankProviderAttempt
from sunshine_extraction.providers.retrieval.base import SemanticRetrievalProviderAttempt
from sunshine_extraction.semantic_index import build_semantic_index
from sunshine_extraction.langgraph_pipeline import run_document_batch, run_document_graph
from sunshine_extraction.domain.documents import SampleFile
from sunshine_extraction.domain.extraction import ExtractionResult, OcrDocumentResult, OcrExecutor, OcrPageResult
from sunshine_extraction.services.tagging import LLMTagInspector


class _KeywordEmbeddingProvider:
    model = "keyword-test"
    dimensions = 2

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            lowered = text.lower()
            if "founders" in lowered or "organized in 1902" in lowered or "history" in lowered:
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return vectors


class _FailingEmbeddingProvider:
    model = "failing-test"
    dimensions = 2

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingProviderError("embedding service unavailable")


class _FakeSemanticRetrievalProvider:
    provider_name = "fake_retrieval"

    def retrieve(self, *, index_path: str | None, query_text: str, limit: int, metadata_filter: dict | None = None):
        del query_text, limit, metadata_filter
        return [
            {"correct_primary_tag": "press_publications", "text": "newspaper clipping", "score": 0.5},
            {"correct_primary_tag": "history_archive_general", "text": "founders history", "score": 0.4},
        ], SemanticRetrievalProviderAttempt(
            provider=self.provider_name,
            status="retrieved",
            index_path=index_path,
            query_count=1,
            result_count=2,
            warnings=[],
            metadata={"local_only": True},
        )


class _FakeRerankProvider:
    provider_name = "cortex"

    def rerank(self, *, query_text: str, documents: list[dict], limit: int):
        del query_text, limit
        return [
            {**documents[1], "rerank_score": 0.99},
            {**documents[0], "rerank_score": 0.12},
        ], RerankProviderAttempt(
            provider=self.provider_name,
            model="rerank-local",
            status="reranked",
            query_count=1,
            input_count=2,
            output_count=2,
            warnings=[],
            metadata={"local_only": True, "base_url": "http://cortex.local"},
        )


class _LocalRawExtractionProvider:
    provider_name = "docling"

    def dependency_status(self) -> dict:
        return {"provider": self.provider_name, "available": True, "local_only": True}

    def extract(self, sample: SampleFile, plan: dict, *, ocr_executor=None, ocr_artifacts=None):
        text = "Sunshine founders history and meeting notes."
        extraction = ExtractionResult(
            sample=sample,
            plan={**plan, "provider": self.provider_name},
            extraction_status="extracted",
            text=text,
            metadata={
                "provider": self.provider_name,
                "local_only": True,
                "docling_structure": {
                    "page_count": 1,
                    "pages": [{"page_number": 1, "text": text, "text_length": len(text), "word_count": len(text.split())}],
                },
            },
            page_count=1,
            warnings=[],
        )
        attempt = ExtractionProviderAttempt(
            provider=self.provider_name,
            status="extracted",
            strategy=plan.get("strategy"),
            seconds=0.1,
            warnings=[],
            metadata={"local_only": True},
        )
        return extraction, attempt


class _TeaLLMTagInspector(LLMTagInspector):
    model = "test-llm"

    def inspect(self, **_kwargs):
        return {
            "llm_status": "inspected",
            "model": self.model,
            "primary_tag": "annual_spring_tea",
            "secondary_tags": ["event_material", "drive_search"],
            "confidence": 0.91,
            "evidence": ["file text mentions tea"],
            "rationale": "Tea evidence is strong.",
            "needs_review": False,
            "warning": None,
        }


class _HistoryLLMTagInspector(LLMTagInspector):
    model = "test-llm"

    def inspect(self, **_kwargs):
        return {
            "llm_status": "inspected",
            "model": self.model,
            "primary_tag": "history_archive_general",
            "secondary_tags": ["history_archive"],
            "confidence": 0.94,
            "evidence": ["file reads like a historical summary"],
            "rationale": "History evidence is strong.",
            "needs_review": False,
            "warning": None,
        }


class _InvalidSecondaryLLMTagInspector(LLMTagInspector):
    model = "test-llm"

    def inspect(self, **_kwargs):
        return {
            "llm_status": "inspected_with_invalid_fields",
            "model": self.model,
            "provider": "test",
            "primary_tag": "annual_spring_tea",
            "secondary_tags": ["event_material"],
            "confidence": 0.92,
            "evidence": ["file text mentions tea"],
            "rationale": "Tea evidence is strong but one secondary tag was invalid.",
            "needs_review": False,
            "review_reason": None,
            "warnings": ["llm_invalid_secondary_tags:not_a_real_tag"],
        }


class _FlakyTeaLLMTagInspector(_TeaLLMTagInspector):
    def __init__(self) -> None:
        self.calls = 0

    def inspect(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary llm failure")
        return super().inspect(**kwargs)


class _SuccessfulOcrExecutor(OcrExecutor):
    def dependency_status(self) -> dict:
        return {"missing": [], "engine": "test-ocr"}

    def ocr_sample(self, sample: SampleFile, plan: dict) -> tuple[OcrDocumentResult, list[OcrPageResult]]:
        text = "Annual tea meeting minutes dental report " * 5
        page = OcrPageResult(
            source_path=sample.source_path,
            relative_path=sample.relative_path,
            sample_path=str(sample.sample_path),
            page_number=1,
            page_count=1,
            ocr_engine="test-ocr",
            ocr_engine_version="1",
            ocr_status="ok",
            text=text,
            text_length=len(text),
            mean_confidence=91.0,
            word_count=len(text.split()),
            image_width=100,
            image_height=100,
            seconds=0.01,
            warnings=[],
        )
        document = OcrDocumentResult(
            source_path=sample.source_path,
            relative_path=sample.relative_path,
            sample_path=str(sample.sample_path),
            ocr_status="ok",
            page_count=1,
            pages_ok=1,
            pages_failed=0,
            total_text_length=len(text),
            mean_confidence=91.0,
            quality="ok",
            seconds=0.01,
            warnings=[],
        )
        return document, [page]


class _RecordingObservabilityProvider:
    provider_name = "recording"

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def dependency_status(self) -> dict:
        return {"provider": self.provider_name, "available": True, "local_only": True}

    def record_event(self, name: str, payload: dict) -> None:
        self.events.append((name, payload))


def test_langgraph_single_file_pipeline_writes_compatible_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "tea.txt"
    source.write_text("Annual Sunshine Tea guest list and event notes.", encoding="utf-8")
    output_dir = tmp_path / "graph-out"
    observability = _RecordingObservabilityProvider()

    result = run_document_graph(
        source,
        source_path="/source/tea.txt",
        relative_path="Sunshine shared folders/Teas/tea.txt",
        output_dir=output_dir,
        embedding_provider=PlaceholderEmbeddingProvider(dimensions=4),
        llm_tag_inspector=_TeaLLMTagInspector(),
        observability_provider=observability,
    )

    final_result = result["final_result"]
    audit_events = [json.loads(line) for line in (output_dir / "graph-audit-events.jsonl").read_text().splitlines()]
    graph_result = json.loads((output_dir / "graph-result.json").read_text())
    pipeline_rows = [json.loads(line) for line in (output_dir / "sample-pipeline-results.jsonl").read_text().splitlines()]
    review_rows = [json.loads(line) for line in (output_dir / "sample-review-queue.jsonl").read_text().splitlines()]
    chunk_rows = [json.loads(line) for line in (output_dir / "sample-chunks.jsonl").read_text().splitlines()]
    embedding_rows = [json.loads(line) for line in (output_dir / "sample-embeddings.jsonl").read_text().splitlines()]
    indexing_rows = [json.loads(line) for line in (output_dir / "sample-indexing.jsonl").read_text().splitlines()]
    validation_rows = [json.loads(line) for line in (output_dir / "sample-extraction-validations.jsonl").read_text().splitlines()]
    repair_rows = [json.loads(line) for line in (output_dir / "sample-extraction-repairs.jsonl").read_text().splitlines()]
    quality_gate_rows = [json.loads(line) for line in (output_dir / "sample-quality-gates.jsonl").read_text().splitlines()]
    semantic_rows = [json.loads(line) for line in (output_dir / "sample-semantic-examples.jsonl").read_text().splitlines()]
    llm_rows = [json.loads(line) for line in (output_dir / "sample-llm-tag-inspections.jsonl").read_text().splitlines()]
    llm_result_rows = [json.loads(line) for line in (output_dir / "sample-llm-tag-inspection-results.jsonl").read_text().splitlines()]
    model_usage_rows = [json.loads(line) for line in (output_dir / "sample-model-usage.jsonl").read_text().splitlines()]
    segment_rows = [json.loads(line) for line in (output_dir / "sample-document-segments.jsonl").read_text().splitlines()]
    chunking_rows = [json.loads(line) for line in (output_dir / "sample-chunking-results.jsonl").read_text().splitlines()]
    structure_rows = [json.loads(line) for line in (output_dir / "sample-structure.jsonl").read_text().splitlines()]
    embedding_result_rows = [json.loads(line) for line in (output_dir / "sample-embedding-results.jsonl").read_text().splitlines()]
    retrieval_result_rows = [json.loads(line) for line in (output_dir / "sample-retrieval-results.jsonl").read_text().splitlines()]
    provider_attempt_rows = [json.loads(line) for line in (output_dir / "sample-provider-attempts.jsonl").read_text().splitlines()]
    parser_rows = [json.loads(line) for line in (output_dir / "sample-parser-results.jsonl").read_text().splitlines()]
    source_identity_rows = [json.loads(line) for line in (output_dir / "sample-source-identity.jsonl").read_text().splitlines()]
    probe_rows = [json.loads(line) for line in (output_dir / "sample-file-probes.jsonl").read_text().splitlines()]
    provider_selection_rows = [json.loads(line) for line in (output_dir / "sample-provider-selections.jsonl").read_text().splitlines()]
    placement_rows = [json.loads(line) for line in (output_dir / "sample-placement-proposals.jsonl").read_text().splitlines()]
    route_rows = [json.loads(line) for line in (output_dir / "sample-route-decisions.jsonl").read_text().splitlines()]
    calibration_rows = [json.loads(line) for line in (output_dir / "sample-confidence-calibrations.jsonl").read_text().splitlines()]
    import_rows = [json.loads(line) for line in (output_dir / "sample-import-results.jsonl").read_text().splitlines()]
    manifest = json.loads((output_dir / "artifact-manifest.json").read_text())
    run_metadata = json.loads((output_dir / "graph-run-metadata.json").read_text())
    manifest_by_name = {artifact["name"]: artifact for artifact in manifest["artifacts"]}

    assert final_result["route_status"] == "route_candidate"
    assert final_result["run_id"] == result["run_id"]
    assert final_result["graph_run_id"] == result["run_id"]
    assert final_result["top_tag_candidate"] == "annual_spring_tea"
    assert final_result["tag_assignment_source"] == "deterministic+llm"
    assert final_result["file_id"] == result["file_id"]
    assert len(final_result["content_sha256"]) == 64
    assert final_result["confidence_calibration"]["status"] == "calibrated"
    assert "semantic_index_missing" in final_result["warnings"]
    assert graph_result["final_result"]["top_tag_candidate"] == "annual_spring_tea"
    assert graph_result["graph_runtime"]["latency_status"] in {"ok", "slow", "over_hard_limit"}
    assert run_metadata["graph_runtime"]["policy"]["raw_provider_storage"] == "artifact_file_by_run"
    assert run_metadata["graph_runtime"]["policy"]["source_files_mutable"] is False
    assert pipeline_rows == [final_result]
    assert review_rows == []
    assert chunk_rows[0]["chunk_kind"] == "text"
    assert embedding_rows[0]["embedding_status"] == "placeholder"
    assert indexing_rows[0]["provider"] == "noop"
    assert indexing_rows[0]["status"] == "skipped"
    assert indexing_rows[0]["chunk_count"] == 1
    assert indexing_rows[0]["placeholder_embedding_count"] == 1
    assert validation_rows[0]["status"] == "ok"
    assert repair_rows[0]["status"] == "not_needed"
    assert quality_gate_rows[0]["quality"] == "ok"
    assert quality_gate_rows[0]["can_chunk"] is True
    assert quality_gate_rows[0]["can_embed"] is True
    assert quality_gate_rows[0]["requires_review"] is False
    assert "validation:ok" in quality_gate_rows[0]["quality_evidence"]
    assert semantic_rows == []
    assert llm_rows[0]["primary_tag"] == "annual_spring_tea"
    assert llm_result_rows[0]["provider"] == "disabled"
    assert llm_result_rows[0]["status"] == "inspected"
    assert llm_result_rows[0]["metadata"]["primary_tag"] == "annual_spring_tea"
    assert segment_rows[0]["segment_type"] == "single_document"
    assert segment_rows[0]["requires_segment_review"] is False
    assert segment_rows[0]["metadata"]["parent_content_sha256"] == source_identity_rows[0]["content_sha256"]
    assert segment_rows[0]["metadata"]["parent_source_path"] == "/source/tea.txt"
    assert chunking_rows[0]["provider"] == "current"
    assert chunking_rows[0]["status"] == "chunked"
    assert chunking_rows[0]["chunk_count"] == 1
    assert chunking_rows[0]["chunking_strategy"] == "fixed_size_text"
    assert structure_rows[0]["provider"] == "current"
    assert embedding_result_rows[0]["provider"] == "local"
    assert embedding_result_rows[0]["status"] == "placeholder"
    assert embedding_result_rows[0]["requested_count"] == 1
    assert embedding_result_rows[0]["embedded_count"] == 1
    assert embedding_result_rows[0]["semantic_quality"] is False
    assert retrieval_result_rows[0]["provider"] == "sqlite_semantic_index"
    assert retrieval_result_rows[0]["status"] == "skipped"
    assert retrieval_result_rows[0]["warnings"] == ["semantic_index_missing"]
    assert structure_rows[0]["text_length"] == len("Annual Sunshine Tea guest list and event notes.")
    assert structure_rows[0]["pages"][0]["quality"] == "text"
    assert provider_attempt_rows[0]["provider"] == "current"
    assert parser_rows[0]["parser_provider"] == "current"
    assert parser_rows[0]["status"] == "extracted"
    assert parser_rows[0]["quality"] == "ok"
    assert parser_rows[0]["text_length"] == len("Annual Sunshine Tea guest list and event notes.")
    assert parser_rows[0]["page_structure_available"] is True
    assert parser_rows[0]["page_text_coverage_rate"] == 1.0
    assert parser_rows[0]["metadata"]["graph_artifact"] is True
    assert source_identity_rows[0]["size_bytes"] == source.stat().st_size
    assert len(source_identity_rows[0]["content_sha256"]) == 64
    assert result["file_id"] == source_identity_rows[0]["file_id"]
    assert probe_rows[0]["media_type"] == "text"
    assert probe_rows[0]["metadata"]["local_only"] is True
    assert provider_selection_rows[0]["selected_provider"] == "current"
    assert provider_selection_rows[0]["provider_chain"] == ["current"]
    assert placement_rows[0]["primary_tag"] == "annual_spring_tea"
    assert placement_rows[0]["proposal"]["placement_status"] == "needs_review"
    assert placement_rows[0]["proposal"]["placement_rule"] == "by_year"
    assert route_rows[0]["route_status"] == "route_candidate"
    assert route_rows[0]["priority"] == "none"
    assert route_rows[0]["review_stage"] == "accepted"
    assert "top_tag:annual_spring_tea" in route_rows[0]["evidence"]
    assert calibration_rows[0]["status"] == "calibrated"
    assert calibration_rows[0]["top_tag"] == "annual_spring_tea"
    assert calibration_rows[0]["calibrated_confidence"] == final_result["tag_confidence"]
    assert calibration_rows[0]["candidate_count"] == len(result["tag_candidates"])
    assert import_rows[0]["import_status"] == "skipped"
    assert import_rows[0]["importer"] == "noop"
    assert manifest_by_name["sample-pipeline-results.jsonl"]["row_count"] == 1
    assert manifest_by_name["sample-route-decisions.jsonl"]["row_count"] == 1
    assert manifest_by_name["sample-llm-tag-inspection-results.jsonl"]["row_count"] == 1
    assert manifest_by_name["sample-confidence-calibrations.jsonl"]["row_count"] == 1
    assert manifest_by_name["sample-document-segments.jsonl"]["row_count"] == 1
    assert manifest_by_name["sample-chunking-results.jsonl"]["row_count"] == 1
    assert manifest_by_name["sample-embedding-results.jsonl"]["row_count"] == 1
    assert manifest_by_name["sample-retrieval-results.jsonl"]["row_count"] == 1
    assert manifest_by_name["sample-parser-results.jsonl"]["row_count"] == 1
    assert manifest_by_name["sample-import-results.jsonl"]["row_count"] == 1
    assert manifest_by_name["graph-run-metadata.json"]["kind"] == "json"
    assert len(manifest_by_name["graph-run-metadata.json"]["sha256"]) == 64
    assert len(manifest_by_name["graph-result.json"]["sha256"]) == 64
    assert manifest_by_name["artifact-manifest.json"]["note"] == "self_referential_manifest"
    assert manifest_by_name["artifact-manifest.json"]["sha256"] is None
    assert {row["purpose"] for row in model_usage_rows} == {"chunk_embedding", "semantic_retrieval_embedding", "tag_inspection"}
    assert [event["node"] for event in audit_events] == [
        "load_file_context",
        "identify_file",
        "probe_file",
        "classify_content_type",
        "plan_extraction",
        "select_extraction_provider",
        "extract_content",
        "validate_extraction",
        "repair_or_escalate_extraction",
        "quality_gate",
        "normalize_document_structure",
        "propose_document_segments",
        "chunk_content",
        "embed_chunks",
        "index_chunks",
        "retrieve_labeled_examples",
        "assign_deterministic_tags",
        "inspect_tags_with_llm",
        "combine_tag_evidence",
        "calibrate_tag_confidence",
        "propose_placement",
        "resolve_route_or_review",
        "persist_outputs",
        "import_run_results",
    ]
    assert [event[0] for event in observability.events] == ["graph.node"] * len(audit_events)
    assert [event[1]["node"] for event in observability.events] == [event["node"] for event in audit_events]
    for artifact in manifest["artifacts"]:
        if artifact["kind"] != "jsonl" or artifact["row_count"] == 0:
            continue
        rows = [json.loads(line) for line in Path(artifact["path"]).read_text(encoding="utf-8").splitlines()]
        assert all(row.get("run_id") is not None for row in rows), artifact["name"]
        assert all(row.get("graph_run_id") == result["run_id"] for row in rows), artifact["name"]


def test_graph_nodes_package_exports_full_v2_node_surface() -> None:
    from sunshine_extraction.graph import nodes

    expected = {
        "_load_file_context",
        "_identify_file",
        "_probe_file",
        "_classify_content_type",
        "_plan_extraction",
        "_select_extraction_provider_node",
        "_extract_content_node",
        "_validate_extraction_node",
        "_repair_or_escalate_extraction_node",
        "_quality_gate",
        "_normalize_document_structure_node",
        "_propose_document_segments_node",
        "_chunk_content_node",
        "_embed_chunks_node",
        "_index_chunks_node",
        "_retrieve_labeled_examples_node",
        "_assign_deterministic_tags",
        "_inspect_tags_with_llm",
        "_combine_tag_evidence",
        "_calibrate_tag_confidence_node",
        "_propose_placement_node",
        "_resolve_route_or_review_node",
        "_persist_outputs",
        "_import_run_results_node",
    }

    assert expected.issubset(set(nodes.__all__))
    assert all(callable(getattr(nodes, name)) for name in expected)


def test_langgraph_probe_routes_image_only_pdf_to_ocr(tmp_path: Path) -> None:
    source = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with source.open("wb") as handle:
        writer.write(handle)
    output_dir = tmp_path / "graph-out"

    result = run_document_graph(
        source,
        source_path="/source/scan.pdf",
        relative_path="Sunshine shared folders/Scrapbooks/scan.pdf",
        output_dir=output_dir,
        embedding_provider=PlaceholderEmbeddingProvider(dimensions=4),
        llm_tag_inspector=_HistoryLLMTagInspector(),
        ocr_executor=_SuccessfulOcrExecutor(),
    )

    probe_rows = [json.loads(line) for line in (output_dir / "sample-file-probes.jsonl").read_text().splitlines()]

    assert probe_rows[0]["image_only_pdf_likelihood"] == 0.95
    assert result["content_class"]["final_class"] == "scanned_document"
    assert result["extraction_plan"]["strategy"] == "ocr_page_level"
    assert result["extraction_plan"]["provider_hints"]["preferred_parser"] == "current"
    assert result["extraction_provider_selection"]["preferred_provider"] == "current"
    assert result["extraction_provider_selection"]["selected_provider"] == "current"
    assert result["extraction_provider_selection"]["provider_chain"] == ["current", "cortex_ocr"]
    assert result["extraction_provider_selection"]["provider_selection_reason"] == "configured_provider_matches_preferred"


def test_langgraph_confidence_calibration_routes_llm_disagreement_to_review(tmp_path: Path) -> None:
    source = tmp_path / "tea.txt"
    source.write_text("Annual Sunshine Tea guest list and event notes.", encoding="utf-8")

    result = run_document_graph(
        source,
        source_path="/source/tea.txt",
        relative_path="Sunshine shared folders/Teas/tea.txt",
        output_dir=tmp_path / "graph-out",
        embedding_provider=PlaceholderEmbeddingProvider(dimensions=4),
        llm_tag_inspector=_HistoryLLMTagInspector(),
    )

    final_result = result["final_result"]

    assert final_result["top_tag_candidate"] == "annual_spring_tea"
    assert final_result["route_status"] == "review_tag_confidence_calibration"
    assert final_result["review_reason"] == "llm_tag_disagreement"
    assert final_result["tag_confidence"] == 0.78
    assert "llm_primary_disagrees:history_archive_general" in final_result["confidence_calibration"]["factors"]


def test_langgraph_propagates_structured_llm_warnings_to_audit_and_review(tmp_path: Path) -> None:
    source = tmp_path / "tea.txt"
    source.write_text("Annual Sunshine Tea guest list and event notes.", encoding="utf-8")
    output_dir = tmp_path / "graph-out"

    result = run_document_graph(
        source,
        source_path="/source/tea.txt",
        relative_path="Sunshine shared folders/Teas/tea.txt",
        output_dir=output_dir,
        embedding_provider=PlaceholderEmbeddingProvider(dimensions=4),
        llm_tag_inspector=_InvalidSecondaryLLMTagInspector(),
    )

    final_result = result["final_result"]
    audit_events = [json.loads(line) for line in (output_dir / "graph-audit-events.jsonl").read_text().splitlines()]
    llm_event = next(event for event in audit_events if event["node"] == "inspect_tags_with_llm")
    review_rows = [json.loads(line) for line in (output_dir / "sample-review-queue.jsonl").read_text().splitlines()]
    model_usage_rows = [json.loads(line) for line in (output_dir / "sample-model-usage.jsonl").read_text().splitlines()]
    llm_usage = next(row for row in model_usage_rows if row["purpose"] == "tag_inspection")

    assert final_result["llm_status"] == "inspected_with_invalid_fields"
    assert final_result["route_status"] == "review_tag_confidence_calibration"
    assert final_result["review_reason"] == "llm_structured_output_invalid"
    assert "llm_invalid_secondary_tags:not_a_real_tag" in final_result["warnings"]
    assert "llm_invalid_secondary_tags:not_a_real_tag" in llm_event["warnings"]
    assert review_rows[0]["review_reason"] == "llm_structured_output_invalid"
    assert llm_usage["status"] == "inspected_with_invalid_fields"
    assert llm_usage["error"] == "llm_invalid_secondary_tags:not_a_real_tag"


def test_langgraph_retrieves_labeled_examples_and_uses_them_as_tag_evidence(tmp_path: Path) -> None:
    labels_db = tmp_path / "labels.sqlite"
    with sqlite3.connect(labels_db) as connection:
        connection.executescript(
            """
            create table golden_labels (
                id integer primary key autoincrement,
                source_path text not null unique,
                relative_path text not null,
                sample_path text,
                extracted_text_snippet text,
                correct_primary_tag text not null,
                correct_secondary_tags_json text not null default '[]',
                notes text,
                updated_at text not null default (datetime('now'))
            );
            """
        )
        connection.execute(
            """
            insert into golden_labels (
                source_path, relative_path, extracted_text_snippet, correct_primary_tag, correct_secondary_tags_json, notes
            ) values (?, ?, ?, ?, ?, ?)
            """,
            (
                "/source/founders.png",
                "History/founders.png",
                "Founders of Sunshine Club organized in 1902 for charitable projects.",
                "history_archive_general",
                '["history_archive", "programs_mission"]',
                "Historical club summary.",
            ),
        )
    semantic_index_path = tmp_path / "semantic.sqlite"
    provider = _KeywordEmbeddingProvider()
    build_semantic_index(labels_db, semantic_index_path, embedding_provider=provider)

    source = tmp_path / "founders.txt"
    source.write_text("Founders of Sunshine Club organized in 1902 to help poor people.", encoding="utf-8")
    result = run_document_graph(
        source,
        source_path="/source/current-founders.txt",
        relative_path="Current yearbook/founders.txt",
        output_dir=tmp_path / "graph-out",
        embedding_provider=provider,
        llm_tag_inspector=LLMTagInspector(),
        semantic_index_path=semantic_index_path,
    )

    final_result = result["final_result"]

    assert final_result["top_tag_candidate"] == "history_archive_general"
    assert final_result["semantic_example_count"] == 1
    assert final_result["tag_assignment_source"] == "deterministic+semantic"
    assert any("semantic_example_agreement:history_archive_general" in evidence for evidence in final_result["tag_evidence"])


def test_langgraph_runtime_accepts_retrieval_and_rerank_provider_injection(tmp_path: Path) -> None:
    source = tmp_path / "founders.txt"
    source.write_text("Founders of Sunshine Club organized in 1902 to help poor people.", encoding="utf-8")
    output_dir = tmp_path / "graph-out"

    result = run_document_graph(
        source,
        source_path="/source/current-founders.txt",
        relative_path="Current yearbook/founders.txt",
        output_dir=output_dir,
        embedding_provider=PlaceholderEmbeddingProvider(dimensions=4),
        llm_tag_inspector=LLMTagInspector(),
        semantic_retrieval_provider=_FakeSemanticRetrievalProvider(),
        rerank_provider=_FakeRerankProvider(),
        semantic_index_path="semantic.sqlite",
    )

    retrieval_rows = [json.loads(line) for line in (output_dir / "sample-retrieval-results.jsonl").read_text().splitlines()]
    semantic_rows = [json.loads(line) for line in (output_dir / "sample-semantic-examples.jsonl").read_text().splitlines()]
    model_usage_rows = [json.loads(line) for line in (output_dir / "sample-model-usage.jsonl").read_text().splitlines()]

    assert result["semantic_examples"][0]["correct_primary_tag"] == "history_archive_general"
    assert semantic_rows[0]["rerank_score"] == 0.99
    assert retrieval_rows[0]["metadata"]["rerank"]["status"] == "reranked"
    assert any(row["purpose"] == "semantic_example_rerank" and row["metadata"]["call_count"] == 1 for row in model_usage_rows)


def test_langgraph_embedding_failure_mode_routes_to_review_without_placeholder_fallback(tmp_path: Path) -> None:
    source = tmp_path / "tea.txt"
    source.write_text("Annual Sunshine Tea guest list and event notes.", encoding="utf-8")
    output_dir = tmp_path / "graph-out"

    result = run_document_graph(
        source,
        source_path="/source/tea.txt",
        relative_path="Sunshine shared folders/Teas/tea.txt",
        output_dir=output_dir,
        embedding_provider=_FailingEmbeddingProvider(),
        embedding_failure_mode="review",
        llm_tag_inspector=_TeaLLMTagInspector(),
    )

    final_result = result["final_result"]
    embedding_rows = [json.loads(line) for line in (output_dir / "sample-embeddings.jsonl").read_text().splitlines()]
    review_rows = [json.loads(line) for line in (output_dir / "sample-review-queue.jsonl").read_text().splitlines()]
    model_usage_rows = [json.loads(line) for line in (output_dir / "sample-model-usage.jsonl").read_text().splitlines()]
    chunk_embedding_usage = next(row for row in model_usage_rows if row["purpose"] == "chunk_embedding")

    assert embedding_rows == []
    assert final_result["embedding_status"] == "none"
    assert final_result["route_status"] == "review_embedding_unavailable"
    assert final_result["review_reason"] == "embedding_quality_unavailable"
    assert "embedding_provider_failed" in final_result["warnings"]
    assert "embedding_quality_unavailable" in final_result["warnings"]
    assert review_rows[0]["review_reason"] == "embedding_quality_unavailable"
    assert chunk_embedding_usage["status"] == "failed"
    assert chunk_embedding_usage["metadata"]["call_count"] == 1
    assert "EmbeddingProviderError" in chunk_embedding_usage["error"]
    assert all(row.get("status") != "placeholder" for row in model_usage_rows)


def test_langgraph_missing_file_persists_failure_state(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pdf"
    output_dir = tmp_path / "graph-out"

    result = run_document_graph(
        missing,
        output_dir=output_dir,
        embedding_provider=PlaceholderEmbeddingProvider(dimensions=4),
        llm_tag_inspector=LLMTagInspector(),
    )

    final_result = result["final_result"]
    audit_events = [json.loads(line) for line in (output_dir / "graph-audit-events.jsonl").read_text().splitlines()]
    graph_result = json.loads((output_dir / "graph-result.json").read_text())
    pipeline_rows = [json.loads(line) for line in (output_dir / "sample-pipeline-results.jsonl").read_text().splitlines()]
    review_rows = [json.loads(line) for line in (output_dir / "sample-review-queue.jsonl").read_text().splitlines()]
    import_rows = [json.loads(line) for line in (output_dir / "sample-import-results.jsonl").read_text().splitlines()]
    manifest = json.loads((output_dir / "artifact-manifest.json").read_text())
    manifest_by_name = {artifact["name"]: artifact for artifact in manifest["artifacts"]}

    assert final_result["route_status"] == "review_failed_extraction"
    assert final_result["review_reason"] == "file_missing"
    assert "file_missing" in final_result["warnings"]
    assert graph_result["errors"][0]["error_type"] == "file_missing"
    assert pipeline_rows == [final_result]
    assert review_rows[0]["review_reason"] == "file_missing"
    assert import_rows[0]["import_status"] == "skipped"
    assert manifest_by_name["sample-pipeline-results.jsonl"]["row_count"] == 1
    assert manifest_by_name["sample-review-queue.jsonl"]["row_count"] == 1
    assert manifest_by_name["sample-import-results.jsonl"]["row_count"] == 1
    assert len(manifest_by_name["graph-result.json"]["sha256"]) == 64
    assert [event["node"] for event in audit_events] == ["load_file_context", "persist_outputs", "import_run_results"]


def test_langgraph_writes_raw_provider_artifact_reference_for_non_current_extractor(tmp_path: Path) -> None:
    source = tmp_path / "docling-source.txt"
    source.write_text("Docling source placeholder.", encoding="utf-8")
    output_dir = tmp_path / "graph-out"

    result = run_document_graph(
        source,
        output_dir=output_dir,
        content_class={"final_class": "scanned_document", "final_status": "accepted"},
        extraction_plan={
            "strategy": "ocr_page_level",
            "document_subtype": "docling_test_scan",
            "provider_hints": {"preferred_parser": "docling"},
        },
        extraction_provider=_LocalRawExtractionProvider(),
        embedding_provider=PlaceholderEmbeddingProvider(dimensions=4),
        llm_tag_inspector=LLMTagInspector(),
    )

    raw_rows = [json.loads(line) for line in (output_dir / "sample-raw-provider-artifacts.jsonl").read_text().splitlines()]
    provider_attempts = [json.loads(line) for line in (output_dir / "sample-provider-attempts.jsonl").read_text().splitlines()]
    extraction_rows = [json.loads(line) for line in (output_dir / "sample-extraction-results.jsonl").read_text().splitlines()]
    model_usage_rows = [json.loads(line) for line in (output_dir / "sample-model-usage.jsonl").read_text().splitlines()]
    manifest = json.loads((output_dir / "artifact-manifest.json").read_text())
    raw_artifact = raw_rows[0]
    raw_payload = json.loads(Path(raw_artifact["path"]).read_text(encoding="utf-8"))
    parser_usage = next(row for row in model_usage_rows if row["purpose"] == "parser_extraction")

    assert result["extraction_result"].metadata["raw_provider_artifact"]["sha256"] == raw_artifact["sha256"]
    assert raw_artifact["kind"] == "raw_provider_snapshot"
    assert raw_artifact["source_path"] == str(source)
    assert raw_artifact["source_relative_path"] == "docling-source.txt"
    assert raw_artifact["sample_path"] == str(source)
    assert raw_artifact["relative_path"].startswith("raw-providers/docling-")
    assert raw_artifact["artifact_relative_path"] == raw_artifact["relative_path"]
    assert Path(raw_artifact["path"]).exists()
    assert raw_payload["provider"] == "docling"
    assert raw_payload["raw_artifact"]["full_sha256"]
    assert provider_attempts[0]["metadata"]["raw_provider_artifact"]["sha256"] == raw_artifact["sha256"]
    assert extraction_rows[0]["metadata"]["raw_provider_artifact"]["path"] == raw_artifact["path"]
    assert parser_usage["provider"] == "docling"
    assert parser_usage["status"] == "ok"
    assert parser_usage["cost_basis"] == "local"
    assert parser_usage["metadata"]["call_count"] == 1
    assert any(artifact["name"] == "sample-raw-provider-artifacts.jsonl" and artifact["row_count"] == 1 for artifact in manifest["artifacts"])


def test_langgraph_batch_aggregates_artifacts_and_continues_after_file_failure(tmp_path: Path) -> None:
    input_root = tmp_path / "qa samples"
    group = input_root / "accepted-image-random-100"
    group.mkdir(parents=True)
    good = group / "001 - tea.txt"
    missing = group / "002 - missing.txt"
    good.write_text("Annual Sunshine Tea guest list and event notes.", encoding="utf-8")
    source_good = "/source/tea.txt"
    source_missing = "/source/missing.txt"
    relative_good = "Sunshine shared folders/Teas/tea.txt"
    relative_missing = "Sunshine shared folders/Teas/missing.txt"
    (group / "index.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"link_name": good.name, "source_path": source_good, "relative_path": relative_good, "number": 1}),
                json.dumps({"link_name": missing.name, "source_path": source_missing, "relative_path": relative_missing, "number": 2}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    corrected = tmp_path / "corrected.jsonl"
    corrected.write_text(
        "\n".join(
            [
                json.dumps({"source_path": source_good, "relative_path": relative_good, "final_class": "document", "final_status": "accepted"}),
                json.dumps({"source_path": source_missing, "relative_path": relative_missing, "final_class": "document", "final_status": "accepted"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    plan = tmp_path / "plan.jsonl"
    plan.write_text(
        "\n".join(
            [
                json.dumps({"source_path": source_good, "relative_path": relative_good, "strategy": "text_extraction", "document_subtype": "text_document"}),
                json.dumps({"source_path": source_missing, "relative_path": relative_missing, "strategy": "text_extraction", "document_subtype": "text_document"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "batch-out"

    summary = run_document_batch(
        input_root,
        output_dir=output_dir,
        corrected_path=corrected,
        plan_path=plan,
        extraction_provider=CurrentExtractionProvider(),
        embedding_provider=PlaceholderEmbeddingProvider(dimensions=4),
        llm_tag_inspector=LLMTagInspector(),
        max_concurrency=2,
        rate_limit_seconds=0,
    )

    results = [json.loads(line) for line in (output_dir / "sample-pipeline-results.jsonl").read_text().splitlines()]
    review_rows = [json.loads(line) for line in (output_dir / "sample-review-queue.jsonl").read_text().splitlines()]
    audit_events = [json.loads(line) for line in (output_dir / "graph-audit-events.jsonl").read_text().splitlines()]
    batch_summary = json.loads((output_dir / "graph-batch-summary.json").read_text())
    pipeline_summary = json.loads((output_dir / "sample-pipeline-summary.json").read_text())
    manifest = json.loads((output_dir / "artifact-manifest.json").read_text())
    manifest_by_name = {artifact["name"]: artifact for artifact in manifest["artifacts"]}

    assert summary["selected_sample_count"] == 2
    assert summary["graph_run_count"] == 2
    assert summary["error_count"] == 1
    assert len(results) == 2
    assert len(review_rows) == 1
    assert review_rows[0]["review_reason"] == "file_missing"
    assert {row["route_status"] for row in results} == {"route_candidate", "review_failed_extraction"}
    assert batch_summary["error_count"] == 1
    assert batch_summary["max_concurrency"] == 2
    assert pipeline_summary["artifact_counts"]["sample-pipeline-results.jsonl"] == 2
    assert pipeline_summary["max_concurrency"] == 2
    assert manifest_by_name["sample-pipeline-results.jsonl"]["row_count"] == 2
    assert manifest_by_name["sample-review-queue.jsonl"]["row_count"] == 1
    assert manifest_by_name["sample-chunking-results.jsonl"]["row_count"] == 1
    assert manifest_by_name["sample-embedding-results.jsonl"]["row_count"] == 1
    assert manifest_by_name["sample-retrieval-results.jsonl"]["row_count"] == 1
    assert manifest_by_name["sample-llm-tag-inspection-results.jsonl"]["row_count"] == 1
    assert manifest_by_name["sample-confidence-calibrations.jsonl"]["row_count"] == 1
    assert manifest_by_name["graph-batch-summary.json"]["kind"] == "json"
    assert len(manifest_by_name["sample-pipeline-summary.json"]["sha256"]) == 64
    assert (output_dir / "graph-runs" / "00001" / "graph-result.json").exists()
    assert (output_dir / "graph-runs" / "00002" / "graph-result.json").exists()
    assert len([event for event in audit_events if event["node"] == "persist_outputs"]) == 2


def test_langgraph_ocr_path_writes_page_and_document_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "scan.jpg"
    source.write_bytes(b"fake image bytes handled by injected ocr executor")
    output_dir = tmp_path / "graph-out"

    result = run_document_graph(
        source,
        source_path="/source/scan.jpg",
        relative_path="Sunshine shared folders/Minutes/scan.jpg",
        output_dir=output_dir,
        content_class={"source_path": "/source/scan.jpg", "relative_path": "Sunshine shared folders/Minutes/scan.jpg", "final_class": "scanned_document", "final_status": "accepted"},
        extraction_plan={"source_path": "/source/scan.jpg", "relative_path": "Sunshine shared folders/Minutes/scan.jpg", "strategy": "ocr_page_level", "document_subtype": "scanned_or_photographed_document"},
        embedding_provider=PlaceholderEmbeddingProvider(dimensions=4),
        llm_tag_inspector=LLMTagInspector(),
        ocr_executor=_SuccessfulOcrExecutor(),
    )

    ocr_pages = [json.loads(line) for line in (output_dir / "sample-ocr-pages.jsonl").read_text().splitlines()]
    ocr_docs = [json.loads(line) for line in (output_dir / "sample-ocr-documents.jsonl").read_text().splitlines()]

    assert result["final_result"]["ocr_status"] == "ok"
    assert result["final_result"]["extraction_status"] == "extracted"
    assert len(ocr_pages) == 1
    assert len(ocr_docs) == 1
    assert ocr_docs[0]["quality"] == "ok"


def test_langgraph_checkpointing_writes_sqlite_checkpoints_and_retry_succeeds(tmp_path: Path) -> None:
    source = tmp_path / "tea.txt"
    source.write_text("Annual Sunshine Tea guest list and event notes.", encoding="utf-8")
    output_dir = tmp_path / "graph-out"
    checkpoint_path = tmp_path / "checkpoints.sqlite"
    inspector = _FlakyTeaLLMTagInspector()

    result = run_document_graph(
        source,
        source_path="/source/tea.txt",
        relative_path="Sunshine shared folders/Teas/tea.txt",
        output_dir=output_dir,
        embedding_provider=PlaceholderEmbeddingProvider(dimensions=4),
        llm_tag_inspector=inspector,
        checkpoint_path=checkpoint_path,
        thread_id="test-thread",
        retry_attempts=2,
    )

    audit_events = [json.loads(line) for line in (output_dir / "graph-audit-events.jsonl").read_text().splitlines()]
    graph_result = json.loads((output_dir / "graph-result.json").read_text())
    llm_event = next(event for event in audit_events if event["node"] == "inspect_tags_with_llm")
    with sqlite3.connect(checkpoint_path) as connection:
        checkpoint_count = connection.execute("select count(*) from checkpoints").fetchone()[0]

    assert result["final_result"]["top_tag_candidate"] == "annual_spring_tea"
    assert inspector.calls == 2
    assert llm_event["attempts"] == 2
    assert graph_result["thread_id"] == "test-thread"
    assert graph_result["checkpoint_path"] == str(checkpoint_path)
    assert checkpoint_count > 0
