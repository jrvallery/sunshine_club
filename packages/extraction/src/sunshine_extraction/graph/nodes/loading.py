"""File loading node for the document graph."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sunshine_extraction.graph.state import DocumentPipelineState
from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.identity import identify_source_file


def _load_file_context(state: DocumentPipelineState) -> dict[str, Any]:
    input_path = Path(state["input_path"])
    if not input_path.exists():
        return {
            "errors": [
                *state.get("errors", []),
                {"node": "load_file_context", "error_type": "file_missing", "message": str(input_path)},
            ],
            "warnings": [*state.get("warnings", []), "file_missing"],
            "route": {"route_status": "review_failed_extraction", "review_reason": "file_missing"},
        }
    sample = SampleFile(
        sample_path=input_path,
        source_path=state.get("source_path") or str(input_path),
        relative_path=state.get("relative_path") or input_path.name,
        sample_group=state.get("sample_group", "single-file"),
        sample_number=state.get("sample_number", 1),
        index_row={"metadata": {"size_bytes": input_path.stat().st_size, **state.get("index_metadata", {})}},
    )
    return {
        "sample": sample,
        "filename": input_path.name,
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
    }

def _identify_file(state: DocumentPipelineState) -> dict[str, Any]:
    identity = identify_source_file(state["sample"])
    return {
        "file_id": identity["file_id"],
        "source_identity": identity,
        "index_metadata": {**state.get("index_metadata", {}), "source_identity": identity},
    }

def _after_load_file_context(state: DocumentPipelineState) -> str:
    return "persist" if state.get("errors") and "sample" not in state else "continue"
