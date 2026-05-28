"""Run-owned raw provider artifact snapshots.

These artifacts preserve provider-specific extraction evidence without putting
large provider payloads directly into normalized JSONL rows.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sunshine_extraction.services.extraction import ExtractionResult
from sunshine_extraction.services.runtime_policy import pipeline_runtime_policy_from_env


def write_raw_provider_artifact(
    output_dir: str | Path,
    extraction: ExtractionResult,
    provider_attempt: dict[str, Any],
) -> dict[str, Any] | None:
    provider = str(provider_attempt.get("provider") or extraction.metadata.get("provider") or "")
    if not provider or provider == "current":
        return None
    policy = pipeline_runtime_policy_from_env()
    max_bytes = int(policy["raw_provider_artifact_max_bytes"])
    preview_bytes = int(policy["raw_provider_inline_preview_bytes"])
    raw_dir = Path(output_dir) / "raw-providers"
    raw_dir.mkdir(parents=True, exist_ok=True)

    full_payload = _payload(extraction, provider_attempt, text_limit=None)
    full_bytes = _json_bytes(full_payload)
    full_sha256 = hashlib.sha256(full_bytes).hexdigest()
    stored_payload = full_payload
    truncated = False
    if len(full_bytes) > max_bytes:
        stored_payload = _payload(extraction, provider_attempt, text_limit=preview_bytes)
        truncated = True
    artifact_name = _artifact_name(provider, extraction)
    artifact_path = raw_dir / artifact_name
    artifact_bytes = _json_bytes(
        {
            **stored_payload,
            "raw_artifact": {
                "schema_version": 1,
                "full_sha256": full_sha256,
                "full_size_bytes": len(full_bytes),
                "truncated": truncated,
                "max_size_bytes": max_bytes,
                "inline_preview_bytes": preview_bytes,
            },
        }
    )
    artifact_path.write_bytes(artifact_bytes)
    return {
        "provider": provider,
        "path": str(artifact_path),
        "relative_path": str(artifact_path.relative_to(Path(output_dir))),
        "kind": "raw_provider_snapshot",
        "exists": True,
        "size_bytes": len(artifact_bytes),
        "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "full_sha256": full_sha256,
        "full_size_bytes": len(full_bytes),
        "truncated": truncated,
    }


def _payload(extraction: ExtractionResult, provider_attempt: dict[str, Any], *, text_limit: int | None) -> dict[str, Any]:
    text = extraction.text or ""
    if text_limit is not None:
        text = text.encode("utf-8")[:text_limit].decode("utf-8", errors="ignore")
    return {
        "source_path": extraction.sample.source_path,
        "relative_path": extraction.sample.relative_path,
        "sample_path": str(extraction.sample.sample_path),
        "provider": provider_attempt.get("provider") or extraction.metadata.get("provider"),
        "strategy": extraction.plan.get("strategy"),
        "extraction_status": extraction.extraction_status,
        "page_count": extraction.page_count,
        "text": text,
        "text_length": len(extraction.text or ""),
        "metadata": extraction.metadata,
        "provider_attempt": provider_attempt,
        "warnings": extraction.warnings,
    }


def _artifact_name(provider: str, extraction: ExtractionResult) -> str:
    identity = "|".join([provider, extraction.sample.source_path, extraction.sample.relative_path, str(extraction.sample.sample_path)])
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{provider}-{digest}.json"


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")
