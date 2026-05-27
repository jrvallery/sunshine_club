"""Compatibility wrapper for the Sunshine document LangGraph pipeline.

The implementation now lives under ``sunshine_extraction.graph``. This module
keeps existing imports and ``python -m sunshine_extraction.langgraph_pipeline``
working while the internals stay organized by responsibility.
"""

from sunshine_extraction.graph.batch import run_document_batch
from sunshine_extraction.graph.build import build_document_graph
from sunshine_extraction.graph.cli import main
from sunshine_extraction.graph.runtime import run_document_graph
from sunshine_extraction.graph.state import DocumentPipelineDeps, DocumentPipelineState

__all__ = [
    "DocumentPipelineDeps",
    "DocumentPipelineState",
    "build_document_graph",
    "main",
    "run_document_batch",
    "run_document_graph",
]


if __name__ == "__main__":
    main()
