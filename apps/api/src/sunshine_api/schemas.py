"""Pydantic request and response models for the Sunshine API.

This module keeps HTTP payload shapes separate from route handlers so the
routers can stay focused on orchestration.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class DocumentPipelineRunRequest(BaseModel):
    input_file: str
    output_dir: str
    source_path: str | None = None
    relative_path: str | None = None
    checkpoint_path: str | None = None
    thread_id: str | None = None
    retry_attempts: int = Field(default=1, ge=1)
    retry_delay_seconds: float = Field(default=0, ge=0)
    enable_llm_tags: bool = False
    llm_tag_provider: str | None = None


class DocumentPipelineRunResponse(BaseModel):
    final_result: dict[str, Any]
    graph_result_path: str
    graph_audit_events_path: str
    checkpoint_path: str | None = None


class ReviewImportRequest(BaseModel):
    output_dir: str
    sample_routed_per_bucket: int = Field(default=0, ge=0)
    sample_seed: int = 20260526


class PostgresImportRequest(BaseModel):
    output_dir: str
    run_key: str
    preset_key: str | None = None


class ReviewDecisionRequest(BaseModel):
    decision: str
    correct_class: str | None = None
    correct_tag: str | None = None
    correct_secondary_tags: list[str] | None = None
    ocr_quality_label: str | None = None
    expected_review_required: bool | None = None
    sensitive_record: bool | None = None
    correct_destination_path: str | None = None
    correct_placement_year: str | None = None
    correct_privacy: str | None = None
    review_stage: str | None = None
    notes: str | None = None
    reviewer: str | None = None
    save_as_golden: bool = True


class SegmentReviewDecisionRequest(BaseModel):
    decision: Literal["accept", "reject", "split", "merge", "defer", "change"]
    notes: str | None = None
    reviewer: str | None = None


class FileReviewRequest(BaseModel):
    review_reason: str = "manual_file_review"


class FileRunRequest(BaseModel):
    output_dir: str | None = None
    embedding_provider: Literal["cortex", "placeholder"] | None = None
    enable_llm_tags: bool = False
    llm_tag_provider: Literal["cortex"] | None = None
    ocr_fallback_provider: Literal["cortex", "disabled"] | None = None
    semantic_index_path: str | None = None
    import_on_success: bool = False
    start: bool = True


class GoldenLabelUpdateRequest(BaseModel):
    content_class: str | None = None
    correct_primary_tag: str | None = None
    correct_secondary_tags: list[str] | None = None
    ocr_quality_label: str | None = None
    expected_review_required: bool | None = None
    sensitive_record: bool | None = None
    correct_destination_path: str | None = None
    correct_placement_year: str | None = None
    correct_privacy: str | None = None
    reviewer: str | None = None
    notes: str | None = None


class ReviewAssignRequest(BaseModel):
    assigned_reviewer: str | None = None
    review_stage: str | None = None
    priority: str | None = None


class ReviewOcrQualityRequest(BaseModel):
    ocr_quality_label: str = "poor"
    review_stage: str | None = "needs_ocr_review"
    notes: str | None = None


class RunStartRequest(BaseModel):
    preset_key: str
    run_role: Literal["baseline", "test", "evaluation"] | None = None
    execution_backend: Literal["subprocess", "temporal"] | None = None
    input_root: str | None = None
    output_dir: str | None = None
    embedding_provider: Literal["cortex", "placeholder"] | None = None
    enable_llm_tags: bool | None = None
    llm_tag_provider: Literal["cortex"] | None = None
    ocr_fallback_provider: Literal["cortex", "disabled"] | None = None
    semantic_index_path: str | None = None
    import_on_success: bool = False
    start: bool = True


class SemanticIndexBuildRequest(BaseModel):
    labels_db: str | None = None
    labels_source: Literal["sqlite", "postgres"] = "sqlite"
    output_db: str | None = None
    limit: int | None = Field(default=None, ge=1)


class QdrantRebuildRequest(BaseModel):
    run_key: str | None = None
    collection: str | None = None
    limit: int | None = Field(default=None, ge=1)


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    collection: str | None = None
    limit: int = Field(default=10, ge=1, le=50)
    metadata_filter: dict[str, Any] | None = None
    run_key: str | None = None
    primary_tag: str | None = None
    content_class: str | None = None
    review_status: str | None = None


class SemanticEvalRequest(BaseModel):
    labels_db: str | None = None
    labels_source: Literal["sqlite", "postgres"] = "sqlite"
    output_dir: str | None = None


class PipelineEvalRequest(BaseModel):
    labels_db: str | None = None
    labels_source: Literal["sqlite", "postgres"] = "sqlite"
    output_dir: str | None = None
    limit: int | None = Field(default=None, ge=1)
    semantic_index_path: str | None = None
    embedding_provider: Literal["placeholder", "cortex"] | None = None
    ocr_fallback_provider: Literal["disabled", "cortex"] | None = None
    disable_semantic_index: bool = False
    enable_llm_tags: bool = False
    enable_ocr: bool = False


class PipelineEvalImportRequest(BaseModel):
    output_dir: str


class ProviderBenchmarkRequest(BaseModel):
    paths: list[str] | None = None
    providers: list[Literal["current", "docling", "mineru", "ragflow_deepdoc", "unstructured"]] = Field(default_factory=lambda: ["current", "docling"])
    output_dir: str | None = None
    sample_manifest: str | None = None
    sample_root: str | None = None
    sample_categories: list[str] | None = None
    sample_limit: int | None = None
    sample_max_megabytes: float | None = None
    max_average_seconds: float | None = 30.0
    background: bool = False


class ProviderBenchmarkImportRequest(BaseModel):
    output_dir: str
    benchmark_key: str | None = None
