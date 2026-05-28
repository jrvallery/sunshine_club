from __future__ import annotations

from pathlib import Path

import pytest

from sunshine_extraction.providers.extraction import CurrentExtractionProvider, DoclingExtractionProvider
from sunshine_extraction.providers.vectorstores import NoopVectorStoreProvider, QdrantVectorStoreProvider
from sunshine_extraction.sample_pipeline import SampleFile, llm_tag_inspector_from_env, ocr_executor_from_env
from sunshine_extraction.services.provider_policy import assert_local_provider
from sunshine_extraction.services.segmentation import propose_document_segments
from sunshine_extraction.services.extraction import ExtractionResult


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


def test_docling_provider_is_optional_and_local_only() -> None:
    status = DoclingExtractionProvider().dependency_status()

    assert status["provider"] == "docling"
    assert status["local_only"] is True
    assert "available" in status


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
    assert "vector_store_not_configured" in result.warnings


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

    assert len(segments) == 1
    assert segments[0]["parent_file_id"] == "file-1"
    assert segments[0]["segment_type"] == "scrapbook_page_group"
    assert segments[0]["page_start"] == 1
    assert segments[0]["page_end"] == 12
    assert segments[0]["requires_segment_review"] is True
