"""Review queue row construction for graph artifacts."""

from __future__ import annotations

from typing import Any


def build_review_queue_rows(final_result: dict[str, Any], document_segments: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    route_status = final_result.get("route_status")
    if route_status == "route_candidate":
        return []
    segments = [segment for segment in (document_segments or []) if segment.get("requires_segment_review")]
    if route_status == "review_segment_boundary" and segments:
        return [_review_queue_row(final_result, segment) for segment in segments]
    return [_review_queue_row(final_result, None)]


def _review_queue_row(final_result: dict[str, Any], segment: dict[str, Any] | None) -> dict[str, Any]:
    row = {
        "sample_path": final_result.get("sample_path"),
        "source_path": final_result.get("source_path"),
        "relative_path": final_result.get("relative_path"),
        "route_status": final_result.get("route_status"),
        "review_reason": final_result.get("review_reason"),
        "final_class": final_result.get("final_class"),
        "extraction_strategy": final_result.get("extraction_strategy"),
        "extraction_status": final_result.get("extraction_status"),
        "quality": final_result.get("quality"),
        "top_tag_candidate": final_result.get("top_tag_candidate"),
        "secondary_tags": final_result.get("secondary_tags", []),
        "tag_confidence": final_result.get("tag_confidence"),
        "warnings": final_result.get("warnings", []),
    }
    if segment:
        row.update(
            {
                "segment_id": segment.get("segment_id"),
                "segment_title": segment.get("segment_title"),
                "segment_type": segment.get("segment_type"),
                "page_start": segment.get("page_start"),
                "page_end": segment.get("page_end"),
                "segment_confidence": segment.get("segment_confidence"),
                "segment_boundary_evidence": segment.get("segment_boundary_evidence", []),
            }
        )
    return row


__all__ = ["build_review_queue_rows"]
