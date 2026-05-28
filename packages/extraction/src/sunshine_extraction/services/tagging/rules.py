"""Deterministic tag-rule service boundary."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from sunshine_extraction.domain.tags import tag_candidate_row
from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import ExtractionResult


@dataclass(frozen=True)
class DeterministicTagRule:
    rule_id: str
    tag: str
    confidence: float
    needles: tuple[str, ...]
    explanation: str
    secondary_tags: tuple[str, ...]


def assign_tag_candidates(sample: SampleFile, corrected: dict[str, Any], plan: dict[str, Any], extraction: ExtractionResult) -> list[dict[str, Any]]:
    if plan["strategy"] == "deferred_technical":
        return []

    haystack = " ".join(
        [
            sample.relative_path,
            sample.sample_path.name,
            str(plan.get("document_subtype") or ""),
            extraction.text[:4000],
            json.dumps(extraction.metadata, sort_keys=True),
            str(corrected.get("review_notes") or ""),
        ]
    ).lower()
    candidates = []
    for rule in load_deterministic_tag_rules():
        matches = [needle for needle in rule.needles if needle in haystack]
        if matches:
            candidates.append(
                tag_candidate_row(
                    source_path=sample.source_path,
                    relative_path=sample.relative_path,
                    tag=rule.tag,
                    confidence=rule.confidence,
                    evidence=[rule.explanation, f"rule:{rule.rule_id}", *[f"matched:{match.strip()}" for match in matches[:3]]],
                    secondary_tags=list(rule.secondary_tags),
                    assignment_source="deterministic",
                    metadata={"rule_id": rule.rule_id, "matched_terms": matches[:3]},
                )
            )
    candidates.sort(key=lambda row: row["confidence"], reverse=True)
    deduped: list[dict[str, Any]] = []
    seen_tags: set[str] = set()
    for candidate in candidates:
        if candidate["tag"] in seen_tags:
            continue
        deduped.append(candidate)
        seen_tags.add(candidate["tag"])
    return deduped[:5]


def load_deterministic_tag_rules(path: str | Path | None = None) -> list[DeterministicTagRule]:
    active_path = path or os.environ.get("SUNSHINE_TAG_RULES_PATH")
    if active_path:
        raw_rules = json.loads(Path(active_path).read_text(encoding="utf-8"))
    else:
        raw_rules = json.loads(resources.files("sunshine_extraction.config").joinpath("tag_rules.json").read_text(encoding="utf-8"))
    if not isinstance(raw_rules, list):
        raise ValueError("deterministic tag rules must be a JSON array")
    return [_rule_from_row(row, index=index) for index, row in enumerate(raw_rules, start=1)]


def _rule_from_row(row: Any, *, index: int) -> DeterministicTagRule:
    if not isinstance(row, dict):
        raise ValueError(f"tag rule {index} must be an object")
    rule_id = _required_string(row, "rule_id", index)
    tag = _required_string(row, "tag", index)
    explanation = _required_string(row, "explanation", index)
    confidence = _confidence(row.get("confidence"), index)
    needles = _string_list(row.get("needles"), "needles", index)
    secondary_tags = _string_list(row.get("secondary_tags", []), "secondary_tags", index)
    if not needles:
        raise ValueError(f"tag rule {rule_id} must include at least one needle")
    return DeterministicTagRule(
        rule_id=rule_id,
        tag=tag,
        confidence=confidence,
        needles=tuple(needle.lower() for needle in needles),
        explanation=explanation,
        secondary_tags=tuple(secondary_tags),
    )


def _required_string(row: dict[str, Any], field: str, index: int) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"tag rule {index} field {field} must be a non-empty string")
    return value.strip()


def _confidence(value: Any, index: int) -> float:
    if isinstance(value, bool):
        raise ValueError(f"tag rule {index} confidence must be numeric")
    try:
        confidence = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"tag rule {index} confidence must be numeric") from error
    if confidence < 0 or confidence > 1:
        raise ValueError(f"tag rule {index} confidence must be between 0 and 1")
    return confidence


def _string_list(value: Any, field: str, index: int) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"tag rule {index} field {field} must be a list")
    strings: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"tag rule {index} field {field} must contain only non-empty strings")
        strings.append(item.strip())
    return strings


__all__ = ["DeterministicTagRule", "assign_tag_candidates", "load_deterministic_tag_rules"]
