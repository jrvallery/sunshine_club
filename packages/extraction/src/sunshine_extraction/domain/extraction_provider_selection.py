"""Auditable extraction provider selection contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ExtractionProviderSelection:
    source_path: str
    relative_path: str
    sample_path: str
    selected_provider: str
    provider_chain: list[str]
    provider_selection_reason: str
    preferred_provider: str
    configured_provider: str
    local_only_required: bool
    skipped_providers: list[dict[str, Any]]
    metadata: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        return asdict(self)
