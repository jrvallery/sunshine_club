"""Model usage row contract for graph audit artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ModelUsageRow:
    source_path: str | None
    relative_path: str | None
    node: str
    purpose: str
    provider: str
    model: str
    status: str
    runtime_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    estimated_cost_usd: float | None
    cost_basis: str
    error: str | None
    metadata: dict[str, Any]

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


def cost_basis(provider: str) -> str:
    normalized = provider.lower()
    if normalized in {"placeholder", "local-placeholder"}:
        return "placeholder"
    return "external" if normalized in {"openai", "gemini", "google", "anthropic"} else "local"
