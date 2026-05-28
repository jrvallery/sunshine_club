"""Typed configuration contracts for future provider/run settings."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    capability: str
    local_only: bool = True
    enabled: bool = True
    hosted: bool = False
    package: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        return asdict(self)
