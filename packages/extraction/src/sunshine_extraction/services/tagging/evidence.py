"""Tag evidence-combination service boundary."""

from __future__ import annotations

from typing import Any

from sunshine_extraction.domain.tags import tag_candidate_row

def combine_tag_candidates(
    deterministic_candidates: list[dict[str, Any]],
    llm_inspection: dict[str, Any],
    semantic_examples: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not _llm_inspection_has_usable_primary(llm_inspection):
        return apply_semantic_example_adjustments(deterministic_candidates, semantic_examples or [])

    primary_tag = llm_inspection["primary_tag"]
    llm_confidence = float(llm_inspection.get("confidence") or 0)
    combined = [dict(candidate) for candidate in deterministic_candidates]
    matched = False
    for candidate in combined:
        if candidate["tag"] == primary_tag:
            matched = True
            candidate["confidence"] = min(0.99, (candidate["confidence"] * 0.65) + (llm_confidence * 0.35) + 0.08)
            candidate["evidence"] = [
                *candidate.get("evidence", []),
                "llm_agreed_with_deterministic_primary",
                *[f"llm:{item}" for item in llm_inspection.get("evidence", [])[:2]],
            ]
            candidate["secondary_tags"] = llm_inspection.get("secondary_tags", [])
            candidate["assignment_source"] = "deterministic+llm"
            break
    if not matched:
        combined.append(
            tag_candidate_row(
                source_path=deterministic_candidates[0]["source_path"] if deterministic_candidates else None,
                relative_path=deterministic_candidates[0]["relative_path"] if deterministic_candidates else None,
                tag=primary_tag,
                confidence=min(0.82, llm_confidence * 0.85),
                evidence=["llm_primary_without_deterministic_agreement", *[f"llm:{item}" for item in llm_inspection.get("evidence", [])[:3]]],
                secondary_tags=llm_inspection.get("secondary_tags", []),
                assignment_source="llm",
            )
        )
    combined.sort(key=lambda row: row["confidence"], reverse=True)
    return apply_semantic_example_adjustments(combined, semantic_examples or [])[:5]


def apply_semantic_example_adjustments(candidates: list[dict[str, Any]], semantic_examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not semantic_examples:
        return candidates
    adjusted = [dict(candidate) for candidate in candidates]
    top_examples = semantic_examples[:5]
    for candidate in adjusted:
        tag = candidate.get("tag")
        matching_examples = [example for example in top_examples if example.get("correct_primary_tag") == tag]
        conflicting_examples = [example for example in top_examples[:3] if example.get("correct_primary_tag") != tag]
        evidence = list(candidate.get("evidence", []))
        if matching_examples:
            best_score = max(float(example.get("score") or 0) for example in matching_examples)
            candidate["confidence"] = min(0.99, float(candidate.get("confidence") or 0) + min(0.06, max(0.0, best_score) * 0.06))
            evidence.append(f"semantic_example_agreement:{tag}:{best_score:.3f}")
            source = str(candidate.get("assignment_source") or "")
            candidate["assignment_source"] = f"{source}+semantic" if source and "semantic" not in source else source or "semantic"
        elif conflicting_examples:
            best_conflict = max(float(example.get("score") or 0) for example in conflicting_examples)
            if best_conflict >= 0.65:
                candidate["confidence"] = max(0.0, float(candidate.get("confidence") or 0) - min(0.05, best_conflict * 0.05))
                evidence.append(f"semantic_example_conflict:{conflicting_examples[0].get('correct_primary_tag')}:{best_conflict:.3f}")
        candidate["evidence"] = evidence

    existing_tags = {candidate.get("tag") for candidate in adjusted}
    for example in top_examples[:3]:
        example_tag = example.get("correct_primary_tag")
        score = float(example.get("score") or 0)
        if example_tag and example_tag not in existing_tags and score >= 0.7:
            adjusted.append(
                tag_candidate_row(
                    source_path=None,
                    relative_path=None,
                    tag=example_tag,
                    confidence=min(0.78, score * 0.72),
                    evidence=[f"semantic_example_only:{example_tag}:{score:.3f}", str(example.get("relative_path") or "")],
                    secondary_tags=example.get("correct_secondary_tags", []),
                    assignment_source="semantic",
                )
            )
            existing_tags.add(example_tag)
    adjusted.sort(key=lambda row: row["confidence"], reverse=True)
    return adjusted


def _llm_inspection_has_usable_primary(llm_inspection: dict[str, Any]) -> bool:
    return llm_inspection.get("llm_status") in {"inspected", "inspected_with_invalid_fields"} and bool(llm_inspection.get("primary_tag"))

__all__ = ["apply_semantic_example_adjustments", "combine_tag_candidates"]
