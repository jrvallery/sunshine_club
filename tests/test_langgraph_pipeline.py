from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sunshine_extraction.embeddings import EmbeddingProviderError, PlaceholderEmbeddingProvider
from sunshine_extraction.semantic_index import build_semantic_index
from sunshine_extraction.langgraph_pipeline import run_document_batch, run_document_graph
from sunshine_extraction.sample_pipeline import LLMTagInspector, OcrDocumentResult, OcrExecutor, OcrPageResult, SampleFile


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


def test_langgraph_single_file_pipeline_writes_compatible_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "tea.txt"
    source.write_text("Annual Sunshine Tea guest list and event notes.", encoding="utf-8")
    output_dir = tmp_path / "graph-out"

    result = run_document_graph(
        source,
        source_path="/source/tea.txt",
        relative_path="Sunshine shared folders/Teas/tea.txt",
        output_dir=output_dir,
        embedding_provider=PlaceholderEmbeddingProvider(dimensions=4),
        llm_tag_inspector=_TeaLLMTagInspector(),
    )

    final_result = result["final_result"]
    audit_events = [json.loads(line) for line in (output_dir / "graph-audit-events.jsonl").read_text().splitlines()]
    graph_result = json.loads((output_dir / "graph-result.json").read_text())
    pipeline_rows = [json.loads(line) for line in (output_dir / "sample-pipeline-results.jsonl").read_text().splitlines()]
    review_rows = [json.loads(line) for line in (output_dir / "sample-review-queue.jsonl").read_text().splitlines()]
    chunk_rows = [json.loads(line) for line in (output_dir / "sample-chunks.jsonl").read_text().splitlines()]
    embedding_rows = [json.loads(line) for line in (output_dir / "sample-embeddings.jsonl").read_text().splitlines()]
    semantic_rows = [json.loads(line) for line in (output_dir / "sample-semantic-examples.jsonl").read_text().splitlines()]
    llm_rows = [json.loads(line) for line in (output_dir / "sample-llm-tag-inspections.jsonl").read_text().splitlines()]
    model_usage_rows = [json.loads(line) for line in (output_dir / "sample-model-usage.jsonl").read_text().splitlines()]

    assert final_result["route_status"] == "route_candidate"
    assert final_result["top_tag_candidate"] == "annual_spring_tea"
    assert final_result["tag_assignment_source"] == "deterministic+llm"
    assert final_result["confidence_calibration"]["status"] == "calibrated"
    assert "semantic_index_missing" in final_result["warnings"]
    assert graph_result["final_result"]["top_tag_candidate"] == "annual_spring_tea"
    assert pipeline_rows == [final_result]
    assert review_rows == []
    assert chunk_rows[0]["chunk_kind"] == "text"
    assert embedding_rows[0]["embedding_status"] == "placeholder"
    assert semantic_rows == []
    assert llm_rows[0]["primary_tag"] == "annual_spring_tea"
    assert {row["purpose"] for row in model_usage_rows} == {"chunk_embedding", "semantic_retrieval_embedding", "tag_inspection"}
    assert [event["node"] for event in audit_events] == [
        "load_file_context",
        "classify_content_type",
        "plan_extraction",
        "extract_content",
        "validate_text_extraction",
        "quality_gate",
        "chunk_content",
        "embed_chunks",
        "retrieve_labeled_examples",
        "assign_deterministic_tags",
        "inspect_tags_with_llm",
        "combine_tag_evidence",
        "calibrate_tag_confidence",
        "resolve_route_or_review",
        "persist_outputs",
    ]


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

    assert final_result["route_status"] == "review_failed_extraction"
    assert final_result["review_reason"] == "file_missing"
    assert "file_missing" in final_result["warnings"]
    assert graph_result["errors"][0]["error_type"] == "file_missing"
    assert pipeline_rows == [final_result]
    assert review_rows[0]["review_reason"] == "file_missing"
    assert [event["node"] for event in audit_events] == ["load_file_context", "persist_outputs"]


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
