"""Typed configuration contracts for future provider/run settings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    local_only: bool = True
    enabled: bool = True
