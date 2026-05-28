"""Typed state contracts for the Sunshine document LangGraph.

The graph state is intentionally explicit: each node reads and writes named
fields so audit output, persistence, and review routing can be traced.
"""

from typing import Any, TypedDict

from sunshine_extraction.embeddings import EmbeddingProvider
from sunshine_extraction.providers.extraction import ExtractionProvider
from sunshine_extraction.providers.vectorstores import VectorStoreProvider
from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import ExtractionResult, OcrExecutor
from sunshine_extraction.services.imports import RunResultsImporter
from sunshine_extraction.services.tagging import LLMTagInspector


class DocumentPipelineState(TypedDict, total=False):
    run_id: str
    file_id: str
    input_path: str
    source_path: str
    relative_path: str
    filename: str
    output_dir: str
    taxonomy_path: str
    sample_group: str
    sample_number: int
    index_metadata: dict[str, Any]
    retry_attempts: int
    retry_delay_seconds: float
    checkpoint_path: str
    thread_id: str
    dashboard_run_id: int

    sample: SampleFile
    source_identity: dict[str, Any]
    file_probe: dict[str, Any]
    content_class: dict[str, Any]
    extraction_plan: dict[str, Any]
    extraction_provider_selection: dict[str, Any]
    extraction_result: ExtractionResult
    extraction_quality: dict[str, Any]
    provider_attempts: list[dict[str, Any]]
    ocr_pages: list[dict[str, Any]]
    ocr_document: dict[str, Any]
    document_structure: dict[str, Any]
    document_segments: list[dict[str, Any]]
    chunks: list[dict[str, Any]]
    embeddings: list[dict[str, Any]]
    indexing_result: dict[str, Any]
    semantic_examples: list[dict[str, Any]]
    deterministic_tag_candidates: list[dict[str, Any]]
    llm_tag_inspection: dict[str, Any]
    model_usage: list[dict[str, Any]]
    tag_candidates: list[dict[str, Any]]
    confidence_calibration: dict[str, Any]
    placement_proposal: dict[str, Any]
    route: dict[str, Any]
    final_result: dict[str, Any]
    import_result: dict[str, Any]

    warnings: list[str]
    errors: list[dict[str, Any]]
    audit_events: list[dict[str, Any]]


class DocumentPipelineDeps(TypedDict, total=False):
    extraction_provider: ExtractionProvider
    vector_store: VectorStoreProvider
    embedding_provider: EmbeddingProvider
    embedding_failure_mode: str
    llm_tag_inspector: LLMTagInspector
    ocr_executor: OcrExecutor
    semantic_index_path: str | None
    run_results_importer: RunResultsImporter
