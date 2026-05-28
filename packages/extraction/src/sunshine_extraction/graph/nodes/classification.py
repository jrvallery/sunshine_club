"""Content classification and extraction planning nodes."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.graph.state import DocumentPipelineState
from sunshine_extraction.services.classification import classify_content_type, plan_extraction


def _classify_content_type(state: DocumentPipelineState) -> dict[str, Any]:
    if state.get("content_class"):
        return {}

    return {"content_class": classify_content_type(state["sample"], file_probe=state.get("file_probe", {}))}

def _plan_extraction(state: DocumentPipelineState) -> dict[str, Any]:
    if state.get("extraction_plan"):
        return {}

    return {"extraction_plan": plan_extraction(state["sample"], state["content_class"], file_probe=state.get("file_probe", {}))}
