"""LLM tag-inspection service boundary."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.sample_pipeline import LLMTagInspector, llm_tag_inspector_from_env


def llm_inspection_row(sample: SampleFile, inspection: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_path": str(sample.sample_path),
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
        **inspection,
    }

__all__ = ["LLMTagInspector", "llm_inspection_row", "llm_tag_inspector_from_env"]
