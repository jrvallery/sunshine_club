from __future__ import annotations

import json
from pathlib import Path

from sunshine_api.review_store import ReviewStore
from sunshine_extraction.embeddings import PlaceholderEmbeddingProvider
from sunshine_extraction.semantic_index import build_semantic_index, search_semantic_index


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_semantic_index_builds_from_golden_labels_and_searches(tmp_path: Path) -> None:
    output_dir = tmp_path / "langgraph-out"
    _write_jsonl(
        output_dir / "sample-pipeline-results.jsonl",
        [
            {
                "sample_path": str(tmp_path / "minutes.pdf"),
                "source_path": "/source/minutes.pdf",
                "relative_path": "Minutes/1992-1993.pdf",
                "route_status": "review_low_confidence_tag",
                "review_reason": "tag_confidence_below_threshold",
                "final_class": "document",
                "extraction_strategy": "text_extraction",
                "extraction_status": "extracted",
                "quality": "ok",
                "top_tag_candidate": "meeting_records",
                "secondary_tags": ["membership"],
                "tag_confidence": 0.71,
                "llm_status": "skipped",
                "warnings": [],
            },
            {
                "sample_path": str(tmp_path / "history.png"),
                "source_path": "/source/history.png",
                "relative_path": "History/founders.png",
                "route_status": "review_low_confidence_tag",
                "review_reason": "tag_confidence_below_threshold",
                "final_class": "scanned_document",
                "extraction_strategy": "ocr_page_level",
                "extraction_status": "extracted",
                "quality": "ok",
                "top_tag_candidate": "history_archive_general",
                "secondary_tags": ["programs_mission"],
                "tag_confidence": 0.86,
                "llm_status": "skipped",
                "warnings": [],
            },
        ],
    )
    _write_jsonl(output_dir / "sample-review-queue.jsonl", [])
    _write_jsonl(
        output_dir / "sample-extraction-results.jsonl",
        [
            {
                "source_path": "/source/minutes.pdf",
                "relative_path": "Minutes/1992-1993.pdf",
                "text": "Meeting minutes, membership records, and officer notes.",
            },
            {
                "source_path": "/source/history.png",
                "relative_path": "History/founders.png",
                "text": "Founders of Sunshine Club and the mission helping people.",
            },
        ],
    )
    store = ReviewStore(tmp_path / "review.sqlite")
    store.import_langgraph_output(output_dir, sample_routed_per_bucket=2)
    for item in store.list_review_items():
        store.record_decision(item["id"], decision="accept", reviewer="james")

    provider = PlaceholderEmbeddingProvider(dimensions=16)
    summary = build_semantic_index(store.db_path, tmp_path / "semantic.sqlite", embedding_provider=provider)
    matches = search_semantic_index(
        tmp_path / "semantic.sqlite",
        "Sunshine Club founders mission history",
        embedding_provider=provider,
        limit=2,
    )

    assert summary["indexed"] == 2
    assert summary["embedding_dimensions"] == 16
    assert len(matches) == 2
    assert {"meeting_records", "history_archive_general"} == {match["correct_primary_tag"] for match in matches}
    assert all("score" in match for match in matches)
