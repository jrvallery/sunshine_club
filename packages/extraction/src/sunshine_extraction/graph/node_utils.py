"""Small graph-node helpers that are shared across phases."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.graph.state import DocumentPipelineState
from sunshine_extraction.services.extraction import ExtractionResult


def _empty_extraction(state: DocumentPipelineState) -> ExtractionResult:
    return ExtractionResult(
        sample=state["sample"],
        plan=state["extraction_plan"],
        extraction_status="failed",
        text="",
        metadata={},
        page_count=None,
        warnings=state.get("warnings", []),
    )

def _unique_strings(values: list[Any]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value)
        if text not in seen:
            seen.add(text)
            unique.append(text)
    return unique

def _llm_inspection_warnings(inspection: dict[str, Any]) -> list[str]:
    warnings: list[Any] = []
    raw_warnings = inspection.get("warnings")
    if isinstance(raw_warnings, list):
        warnings.extend(raw_warnings)
    elif raw_warnings:
        warnings.append(raw_warnings)
    if inspection.get("warning"):
        warnings.append(inspection["warning"])
    return _unique_strings(warnings)
