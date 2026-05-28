"""Chunking node implementation."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.graph.state import DocumentPipelineDeps, DocumentPipelineState
from sunshine_extraction.services.segmentation.page_grouping import attach_segment_ids_to_chunks


def _chunk_content_node(state: DocumentPipelineState, deps: DocumentPipelineDeps) -> dict[str, Any]:
    chunks, attempt = deps["chunking_provider"].chunk(state["extraction_result"], state["extraction_quality"])
    return {
        "chunks": attach_segment_ids_to_chunks(chunks, state.get("document_segments", [])),
        "chunking_result": attempt.as_row(),
    }
