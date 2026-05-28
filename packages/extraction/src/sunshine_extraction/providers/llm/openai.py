"""Hosted OpenAI LLM provider policy boundary."""

from __future__ import annotations


class HostedOpenAILLMTagInspector:
    def __init__(self, *_args, **_kwargs) -> None:
        raise ValueError("Hosted OpenAI LLM tag inspection is not allowed; use the local Cortex provider")


__all__ = ["HostedOpenAILLMTagInspector"]
