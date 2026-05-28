"""Graph construction for the Sunshine document pipeline."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from sunshine_extraction.graph.node_runtime import _run_node
from sunshine_extraction.graph.nodes.classification import _classify_content_type, _plan_extraction
from sunshine_extraction.graph.nodes.chunking import _chunk_content_node
from sunshine_extraction.graph.nodes.embeddings import _embed_chunks_node
from sunshine_extraction.graph.nodes.extraction import (
    _extract_content_node,
    _select_extraction_provider_node,
)
from sunshine_extraction.graph.nodes.indexing import _index_chunks_node
from sunshine_extraction.graph.nodes.loading import _after_load_file_context, _identify_file, _load_file_context
from sunshine_extraction.graph.nodes.persistence import _import_run_results_node, _persist_outputs
from sunshine_extraction.graph.nodes.placement import _propose_placement_node
from sunshine_extraction.graph.nodes.probing import _probe_file
from sunshine_extraction.graph.nodes.quality import _after_quality_gate, _quality_gate, _repair_or_escalate_extraction_node, _validate_extraction_node
from sunshine_extraction.graph.nodes.retrieval import _retrieve_labeled_examples_node
from sunshine_extraction.graph.nodes.routing import _resolve_route_or_review_node
from sunshine_extraction.graph.nodes.segmentation import _normalize_document_structure_node, _propose_document_segments_node
from sunshine_extraction.graph.nodes.tagging import _assign_deterministic_tags, _calibrate_tag_confidence_node, _combine_tag_evidence, _inspect_tags_with_llm
from sunshine_extraction.graph.state import DocumentPipelineDeps, DocumentPipelineState
from sunshine_extraction.graph.deps import _resolve_deps

def build_document_graph(deps: DocumentPipelineDeps | None = None, *, checkpointer: Any | None = None) -> Any:
    active_deps = deps or _resolve_deps()
    builder = StateGraph(DocumentPipelineState)
    observability_provider = active_deps.get("observability_provider")

    def add_node(name: str, func: Any) -> None:
        builder.add_node(name, lambda state, node_name=name, node_func=func: _run_node(node_name, state, node_func, observability_provider=observability_provider))

    add_node("load_file_context", _load_file_context)
    add_node("identify_file", _identify_file)
    add_node("probe_file", _probe_file)
    add_node("classify_content_type", _classify_content_type)
    add_node("plan_extraction", _plan_extraction)
    add_node("select_extraction_provider", lambda active: _select_extraction_provider_node(active, active_deps))
    add_node("extract_content", lambda active: _extract_content_node(active, active_deps))
    add_node("validate_extraction", _validate_extraction_node)
    add_node("repair_or_escalate_extraction", lambda active: _repair_or_escalate_extraction_node(active, active_deps))
    add_node("quality_gate", _quality_gate)
    add_node("normalize_document_structure", _normalize_document_structure_node)
    add_node("propose_document_segments", _propose_document_segments_node)
    add_node("chunk_content", lambda active: _chunk_content_node(active, active_deps))
    add_node("embed_chunks", lambda active: _embed_chunks_node(active, active_deps))
    add_node("index_chunks", lambda active: _index_chunks_node(active, active_deps))
    add_node("retrieve_labeled_examples", lambda active: _retrieve_labeled_examples_node(active, active_deps))
    add_node("assign_deterministic_tags", _assign_deterministic_tags)
    add_node("inspect_tags_with_llm", lambda active: _inspect_tags_with_llm(active, active_deps))
    add_node("combine_tag_evidence", _combine_tag_evidence)
    add_node("calibrate_tag_confidence", _calibrate_tag_confidence_node)
    add_node("propose_placement", _propose_placement_node)
    add_node("resolve_route_or_review", _resolve_route_or_review_node)
    add_node("persist_outputs", _persist_outputs)
    add_node("import_run_results", lambda active: _import_run_results_node(active, active_deps))

    builder.add_edge(START, "load_file_context")
    builder.add_conditional_edges(
        "load_file_context",
        _after_load_file_context,
        {"continue": "identify_file", "persist": "persist_outputs"},
    )
    builder.add_edge("identify_file", "probe_file")
    builder.add_edge("probe_file", "classify_content_type")
    builder.add_edge("classify_content_type", "plan_extraction")
    builder.add_edge("plan_extraction", "select_extraction_provider")
    builder.add_edge("select_extraction_provider", "extract_content")
    builder.add_edge("extract_content", "validate_extraction")
    builder.add_edge("validate_extraction", "repair_or_escalate_extraction")
    builder.add_edge("repair_or_escalate_extraction", "quality_gate")
    builder.add_conditional_edges(
        "quality_gate",
        _after_quality_gate,
        {"chunk": "normalize_document_structure", "route": "assign_deterministic_tags"},
    )
    builder.add_edge("normalize_document_structure", "propose_document_segments")
    builder.add_edge("propose_document_segments", "chunk_content")
    builder.add_edge("chunk_content", "embed_chunks")
    builder.add_edge("embed_chunks", "index_chunks")
    builder.add_edge("index_chunks", "retrieve_labeled_examples")
    builder.add_edge("retrieve_labeled_examples", "assign_deterministic_tags")
    builder.add_edge("assign_deterministic_tags", "inspect_tags_with_llm")
    builder.add_edge("inspect_tags_with_llm", "combine_tag_evidence")
    builder.add_edge("combine_tag_evidence", "calibrate_tag_confidence")
    builder.add_edge("calibrate_tag_confidence", "propose_placement")
    builder.add_edge("propose_placement", "resolve_route_or_review")
    builder.add_edge("resolve_route_or_review", "persist_outputs")
    builder.add_edge("persist_outputs", "import_run_results")
    builder.add_edge("import_run_results", END)
    return builder.compile(checkpointer=checkpointer)
