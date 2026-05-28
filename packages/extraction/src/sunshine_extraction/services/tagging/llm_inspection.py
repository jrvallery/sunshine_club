"""LLM tag-inspection service boundary."""

from __future__ import annotations

import json
import os
from typing import Any

from sunshine_extraction.domain.extraction import ExtractionResult
from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.tagging.taxonomy import TaxonomyOptions

DEFAULT_CORTEX_BASE_URL = "https://cortex.vallery.net"
DEFAULT_CORTEX_MODEL = "gemma4-26b"


class LLMTagInspector:
    model: str = "disabled"

    def inspect(
        self,
        *,
        sample: SampleFile,
        corrected: dict[str, Any],
        plan: dict[str, Any],
        extraction: ExtractionResult,
        taxonomy: TaxonomyOptions,
        deterministic_candidates: list[dict[str, Any]],
        semantic_examples: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "llm_status": "skipped",
            "model": self.model,
            "provider": "disabled",
            "primary_tag": None,
            "secondary_tags": [],
            "confidence": 0.0,
            "evidence": [],
            "rationale": "LLM tag inspection disabled.",
            "needs_review": False,
            "warning": None,
        }


class OpenAICompatibleLLMTagInspector(LLMTagInspector):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        provider_name: str = "openai-compatible",
        timeout_seconds: float = 120,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required for OpenAI-compatible LLM tag inspection")
        if not model:
            raise ValueError("model is required for OpenAI-compatible LLM tag inspection")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.provider_name = provider_name
        self.timeout_seconds = timeout_seconds
        self._client: Any | None = None

    def inspect(
        self,
        *,
        sample: SampleFile,
        corrected: dict[str, Any],
        plan: dict[str, Any],
        extraction: ExtractionResult,
        taxonomy: TaxonomyOptions,
        deterministic_candidates: list[dict[str, Any]],
        semantic_examples: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        prompt = build_llm_tag_prompt(sample, corrected, plan, extraction, taxonomy, deterministic_candidates, semantic_examples or [])
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            response = self._chat_client().invoke(
                [
                    SystemMessage(
                        content=(
                            "You classify Sunshine Club files. Return only valid JSON matching the requested schema. "
                            "Do not include markdown fences or commentary."
                        )
                    ),
                    HumanMessage(content=prompt),
                ]
            )
            payload = extract_json_object(message_content_to_text(response.content))
            inspection = normalize_llm_inspection(json.loads(payload), taxonomy, model=self.model, provider=self.provider_name)
            inspection.update(chat_response_usage_fields(response))
            return inspection
        except Exception as error:  # noqa: BLE001 - every file needs an auditable failure row.
            return {
                "llm_status": "failed",
                "model": self.model,
                "provider": self.provider_name,
                "primary_tag": None,
                "secondary_tags": [],
                "confidence": 0.0,
                "evidence": [],
                "rationale": "LLM tag inspection failed.",
                "needs_review": True,
                "warning": f"llm_tag_inspection_failed:{type(error).__name__}",
            }

    def _chat_client(self) -> Any:
        if self._client is None:
            from langchain_openai import ChatOpenAI

            kwargs: dict[str, Any] = {
                "model": self.model,
                "api_key": self.api_key,
                "temperature": 0,
                "timeout": self.timeout_seconds,
                "max_retries": 1,
                "max_completion_tokens": 1024,
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = ChatOpenAI(**kwargs)
        return self._client


def llm_tag_inspector_from_env(*, enabled: bool = True, provider_override: str | None = None) -> LLMTagInspector:
    if not enabled:
        return LLMTagInspector()

    provider_name = (provider_override or os.environ.get("SUNSHINE_LLM_TAG_PROVIDER", "")).strip().lower()
    if provider_name in {"", "disabled", "none"}:
        return LLMTagInspector()
    if provider_name == "auto":
        if os.environ.get("CORTEX_API_KEY") or os.environ.get("CORTEX_OPENAI_API_KEY") or os.environ.get("CORTEX_MODEL"):
            provider_name = "cortex"
        else:
            return LLMTagInspector()
    if provider_name in {"cortex", "openai-compatible"}:
        try:
            return OpenAICompatibleLLMTagInspector(
                api_key=os.environ.get("CORTEX_API_KEY") or os.environ.get("CORTEX_OPENAI_API_KEY", ""),
                model=os.environ.get("CORTEX_MODEL", DEFAULT_CORTEX_MODEL),
                base_url=os.environ.get("CORTEX_OPENAI_BASE_URL") or cortex_openai_base_url(os.environ.get("CORTEX_BASE_URL", DEFAULT_CORTEX_BASE_URL)),
                provider_name="cortex",
                timeout_seconds=float(os.environ.get("SUNSHINE_LLM_TAG_TIMEOUT_SECONDS", "120")),
            )
        except ValueError:
            return LLMTagInspector()
    if provider_name == "openai":
        return LLMTagInspector()
    return LLMTagInspector()


def build_llm_tag_prompt(
    sample: SampleFile,
    corrected: dict[str, Any],
    plan: dict[str, Any],
    extraction: ExtractionResult,
    taxonomy: TaxonomyOptions,
    deterministic_candidates: list[dict[str, Any]],
    semantic_examples: list[dict[str, Any]] | None = None,
) -> str:
    primary_lines = "\n".join(
        f"- {tag}: {taxonomy.primary_definitions.get(tag, '')}"
        for tag in taxonomy.primary_tags
    )
    context = {
        "relative_path": sample.relative_path,
        "filename": sample.sample_path.name,
        "final_class": corrected.get("final_class"),
        "document_subtype": plan.get("document_subtype"),
        "extraction_strategy": plan.get("strategy"),
        "extraction_status": extraction.extraction_status,
        "metadata": extraction.metadata,
        "deterministic_candidates": deterministic_candidates[:5],
        "nearest_human_labeled_examples": (semantic_examples or [])[:5],
        "text_excerpt": extraction.text[:3500],
    }
    return (
        "Classify this Sunshine Club file for routing and retrieval.\n"
        "Choose exactly one primary_tag from the allowed primary tags. Choose zero to five secondary_tags "
        "from the allowed secondary tags. Base the decision only on the provided path, metadata, text excerpt, "
        "deterministic candidates, and nearest human-labeled examples. Treat human-labeled examples as precedent, "
        "but do not copy them when the current file evidence differs. If evidence is weak or examples conflict, "
        "lower confidence and set needs_review=true.\n\n"
        "Return only a JSON object with these keys: primary_tag, secondary_tags, confidence, evidence, competing_tags, "
        "rationale, needs_review, review_reason. competing_tags must be zero to three alternate primary tag keys. "
        "When needs_review is true, review_reason must briefly explain why. Do not include markdown or any text outside the JSON object.\n\n"
        f"Allowed primary tags:\n{primary_lines}\n\n"
        f"Allowed secondary tags:\n{', '.join(taxonomy.secondary_tags)}\n\n"
        f"File context JSON:\n{json.dumps(context, sort_keys=True)}"
    )


def llm_tag_schema(taxonomy: TaxonomyOptions) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "primary_tag": {"type": "string", "enum": taxonomy.primary_tags},
            "secondary_tags": {
                "type": "array",
                "items": {"type": "string", "enum": taxonomy.secondary_tags},
                "maxItems": 5,
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            "competing_tags": {
                "type": "array",
                "items": {"type": "string", "enum": taxonomy.primary_tags},
                "maxItems": 3,
            },
            "rationale": {"type": "string"},
            "needs_review": {"type": "boolean"},
            "review_reason": {"type": "string"},
        },
        "required": ["primary_tag", "secondary_tags", "confidence", "evidence", "competing_tags", "rationale", "needs_review", "review_reason"],
    }


def normalize_llm_inspection(payload: dict[str, Any], taxonomy: TaxonomyOptions, *, model: str, provider: str = "unknown") -> dict[str, Any]:
    primary_tag = payload.get("primary_tag")
    if primary_tag not in taxonomy.primary_tags:
        primary_tag = None
    raw_secondary_tags = [tag for tag in payload.get("secondary_tags", []) if isinstance(tag, str)]
    invalid_secondary_tags = [tag for tag in raw_secondary_tags if tag not in taxonomy.secondary_tags]
    secondary_tags = [tag for tag in raw_secondary_tags if tag in taxonomy.secondary_tags][:5]
    confidence = payload.get("confidence", 0)
    if not isinstance(confidence, int | float):
        confidence = 0
    evidence = [str(item) for item in payload.get("evidence", [])[:5]]
    raw_competing_tags = [tag for tag in payload.get("competing_tags", []) if isinstance(tag, str)]
    invalid_competing_tags = [tag for tag in raw_competing_tags if tag not in taxonomy.primary_tags]
    competing_tags = [tag for tag in raw_competing_tags if tag in taxonomy.primary_tags and tag != primary_tag][:3]
    needs_review = bool(payload.get("needs_review", False))
    review_reason = str(payload.get("review_reason") or "").strip()
    warnings: list[str] = []
    if primary_tag is None:
        review_reason = review_reason or "llm_primary_tag_invalid"
        warnings.append("llm_primary_tag_invalid")
    elif needs_review:
        review_reason = review_reason or "llm_requested_review"
    if invalid_secondary_tags:
        warnings.append(f"llm_invalid_secondary_tags:{','.join(invalid_secondary_tags[:5])}")
    if invalid_competing_tags:
        warnings.append(f"llm_invalid_competing_tags:{','.join(invalid_competing_tags[:5])}")
    llm_status = "inspected"
    if primary_tag is None:
        llm_status = "invalid"
    elif warnings:
        llm_status = "inspected_with_invalid_fields"
    return {
        "llm_status": llm_status,
        "model": model,
        "provider": provider,
        "primary_tag": primary_tag,
        "secondary_tags": secondary_tags,
        "invalid_secondary_tags": invalid_secondary_tags[:5],
        "confidence": max(0.0, min(float(confidence), 1.0)),
        "evidence": evidence,
        "competing_tags": competing_tags,
        "invalid_competing_tags": invalid_competing_tags[:5],
        "rationale": str(payload.get("rationale", "")),
        "needs_review": needs_review,
        "review_reason": review_reason or None,
        "warnings": warnings,
        "warning": warnings[0] if warnings else None,
    }


def llm_inspection_row(sample: SampleFile, inspection: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_path": str(sample.sample_path),
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
        **inspection,
    }


def message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content)


def chat_response_usage_fields(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage_metadata", None)
    if not isinstance(usage, dict):
        metadata = getattr(response, "response_metadata", None)
        if isinstance(metadata, dict):
            usage = metadata.get("token_usage") or metadata.get("usage")
    if not isinstance(usage, dict):
        return {}
    prompt_tokens = optional_positive_int(usage.get("input_tokens") or usage.get("prompt_tokens"))
    output_tokens = optional_positive_int(usage.get("output_tokens") or usage.get("completion_tokens"))
    total_tokens = optional_positive_int(usage.get("total_tokens"))
    fields: dict[str, int] = {}
    if prompt_tokens is not None:
        fields["input_tokens"] = prompt_tokens
    if output_tokens is not None:
        fields["output_tokens"] = output_tokens
    if total_tokens is not None:
        fields["total_tokens"] = total_tokens
    elif prompt_tokens is not None or output_tokens is not None:
        fields["total_tokens"] = int(prompt_tokens or 0) + int(output_tokens or 0)
    return fields


def optional_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float) and value >= 0:
        return int(value)
    return None


def extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise json.JSONDecodeError("No JSON object found in LLM response", stripped, 0)
    return stripped[start : end + 1]


def cortex_openai_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


__all__ = [
    "LLMTagInspector",
    "OpenAICompatibleLLMTagInspector",
    "build_llm_tag_prompt",
    "chat_response_usage_fields",
    "cortex_openai_base_url",
    "extract_json_object",
    "llm_inspection_row",
    "llm_tag_inspector_from_env",
    "llm_tag_schema",
    "message_content_to_text",
    "normalize_llm_inspection",
    "optional_positive_int",
]
