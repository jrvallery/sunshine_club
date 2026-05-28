"""Vector index update node."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.graph.state import DocumentPipelineDeps, DocumentPipelineState
from sunshine_extraction.services.indexing import index_chunks


def _index_chunks_node(state: DocumentPipelineState, deps: DocumentPipelineDeps) -> dict[str, Any]:
    result = index_chunks(state.get("chunks", []), state.get("embeddings", []), deps["vector_store"])
    warnings = [*state.get("warnings", []), *result.get("warnings", [])]
    return {"indexing_result": result, "warnings": warnings}
