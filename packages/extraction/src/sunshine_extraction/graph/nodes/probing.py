"""Technical file probing nodes."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.graph.state import DocumentPipelineState
from sunshine_extraction.providers.probe import NativeFileProbeProvider


def _probe_file(state: DocumentPipelineState) -> dict[str, Any]:
    probe = NativeFileProbeProvider().probe(state["sample"])
    warnings = [*state.get("warnings", []), *probe.get("warnings", [])]
    return {"file_probe": probe, "warnings": warnings}
