"""Route decision row contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class RouteDecision:
    source_path: str
    relative_path: str
    sample_path: str
    route_status: str
    review_reason: Any
    priority: str
    review_stage: str
    accepted: bool
    evidence: list[str]
    metadata: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        return asdict(self)
