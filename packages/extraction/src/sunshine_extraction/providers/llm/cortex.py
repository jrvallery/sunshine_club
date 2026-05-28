"""Cortex LLM tag inspector for local OpenAI-compatible infrastructure."""

from __future__ import annotations

from sunshine_extraction.services.tagging.llm_inspection import DEFAULT_CORTEX_BASE_URL, DEFAULT_CORTEX_MODEL, OpenAICompatibleLLMTagInspector, cortex_openai_base_url


class CortexLLMTagInspector(OpenAICompatibleLLMTagInspector):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_CORTEX_MODEL,
        base_url: str = DEFAULT_CORTEX_BASE_URL,
        timeout_seconds: float = 120,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=cortex_openai_base_url(base_url),
            provider_name="cortex",
            timeout_seconds=timeout_seconds,
        )


__all__ = ["CortexLLMTagInspector"]
