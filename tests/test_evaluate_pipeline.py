from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sunshine_extraction.embeddings import PlaceholderEmbeddingProvider
from sunshine_extraction.evaluate_pipeline import run_golden_pipeline_evaluation
from sunshine_extraction.sample_pipeline import LLMTagInspector


class _TeaLLMTagInspector(LLMTagInspector):
    model = "test-llm"

    def inspect(self, **_kwargs):
        return {
            "llm_status": "inspected",
            "provider": "test",
            "model": self.model,
            "primary_tag": "annual_spring_tea",
            "secondary_tags": ["event_material"],
            "confidence": 0.91,
            "evidence": ["test inspection"],
            "rationale": "Test model always returns tea.",
            "needs_review": False,
            "warning": None,
        }


def test_golden_pipeline_evaluation_runs_graph_and_writes_artifacts(tmp_path: Path) -> None:
    tea = tmp_path / "tea.txt"
    tea.write_text("Annual Sunshine Tea guest list and event notes.", encoding="utf-8")
    history = tmp_path / "history.txt"
    history.write_text("Annual Sunshine Tea planning notes with guest list details.", encoding="utf-8")
    labels_db = tmp_path / "labels.sqlite"
    with sqlite3.connect(labels_db) as connection:
        connection.executescript(
            """
            create table golden_labels (
                id integer primary key autoincrement,
                source_path text not null unique,
                relative_path text not null,
                sample_path text,
                extracted_text_snippet text,
                correct_primary_tag text not null,
                correct_secondary_tags_json text not null default '[]',
                content_class text,
                ocr_quality_label text,
                expected_review_required integer,
                sensitive_record integer,
                correct_destination_path text,
                correct_placement_year text,
                correct_privacy text,
                notes text,
                updated_at text not null default (datetime('now'))
            );
            """
        )
        connection.executemany(
            """
            insert into golden_labels (
                source_path, relative_path, sample_path, correct_primary_tag,
                correct_secondary_tags_json, content_class, ocr_quality_label,
                expected_review_required, sensitive_record, correct_destination_path,
                correct_placement_year, correct_privacy, notes
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "/source/tea.txt",
                    "Sunshine shared folders/Teas/tea.txt",
                    str(tea),
                    "annual_spring_tea",
                    '["event_material"]',
                    "document",
                    "ok",
                    0,
                    0,
                    "90_Intake_Needs_Review/05_Events",
                    None,
                    "club_internal",
                    "Known tea event material.",
                ),
                (
                    "/source/history.txt",
                    "Sunshine shared folders/Teas/misfiled-history.txt",
                    str(history),
                    "history_archive_general",
                    '["history_archive"]',
                    "document",
                    "ok",
                    1,
                    1,
                    "06_History_Archive",
                    None,
                    "public",
                    "Known historical summary.",
                ),
            ],
        )

    output_dir = tmp_path / "eval-out"
    summary = run_golden_pipeline_evaluation(
        labels_db,
        output_dir=output_dir,
        embedding_provider=PlaceholderEmbeddingProvider(dimensions=4),
        llm_tag_inspector=_TeaLLMTagInspector(),
        semantic_index_path=None,
    )

    assert summary["total_golden_labels"] == 2
    assert summary["evaluated_predictions"] == 2
    assert summary["primary_accuracy"] == 0.5
    assert summary["content_class_accuracy"] == 1.0
    assert summary["ocr_quality_accuracy"] == 1.0
    assert summary["ocr_fallback_rate"] == 0.0
    assert summary["review_routing_precision"] == 0.5
    assert summary["review_routing_recall"] == 1.0
    assert summary["review_false_accepts"] == 0
    assert summary["review_false_reviews"] == 1
    assert summary["llm_structured_output_validity_rate"] == 1.0
    assert summary["placement_destination_accuracy"] == 0.5
    assert summary["privacy_accuracy"] == 0.5
    assert summary["secondary_precision"] == 0.5
    assert summary["secondary_recall"] == 0.5
    assert summary["failure_count"] == 2
    assert summary["embedding_success_rate"] == 0.0
    assert summary["semantic_same_family_top5_rate"] == 0.0
    assert summary["high_risk_primary_accuracy_min"] is None
    assert summary["source_file_mutations"] == 0
    assert summary["golden_label_readiness"]["ready"] is False
    assert summary["golden_label_readiness"]["total_golden_labels"] == 2
    assert summary["golden_label_readiness"]["minimum_label_count"] == 75
    assert summary["golden_label_readiness"]["label_count_ready"] is False
    assert summary["golden_label_readiness"]["primary_label_counts"] == {
        "annual_spring_tea": 1,
        "history_archive_general": 1,
    }
    assert "meeting_records" in summary["golden_label_readiness"]["missing_primary_tags"]
    assert "meeting_records" in summary["golden_label_readiness"]["underrepresented_high_risk_tags"]
    assert summary["primary_tag_metrics"]["annual_spring_tea"]["accuracy"] == 1.0
    assert summary["primary_tag_metrics"]["history_archive_general"]["accuracy"] == 0.0
    assert summary["confidence_bucket_metrics"]["high"]["total"] == 2
    assert summary["confidence_bucket_metrics"]["high"]["primary_accuracy"] == 0.5
    assert summary["confidence_bucket_metrics"]["high"]["false_reviews"] == 1
    assert summary["acceptance_gate"]["status"] == "fail"
    assert {check["name"] for check in summary["acceptance_gate"]["blocking_checks"]} == {
        "embedding_placeholder_calls",
        "golden_label_count",
        "high_risk_label_min_count",
        "high_risk_primary_accuracy",
        "primary_taxonomy_coverage",
        "primary_accuracy",
        "placement_destination_accuracy",
        "privacy_accuracy",
    }
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "source_file_mutations")["status"] == "pass"
    assert summary["by_failure_reason"] == {
        "embedding_quality_unavailable": 2,
        "placement_destination_mismatch": 1,
        "primary_tag_mismatch": 1,
        "privacy_mismatch": 1,
        "review_routing_mismatch": 1,
        "semantic_retrieval_missing": 1,
    }
    assert summary["model_usage"]["by_purpose"] == {
        "chunk_embedding": 2,
        "semantic_retrieval_embedding": 2,
        "tag_inspection": 2,
    }
    assert summary["model_usage"]["embedding_attempted_calls"] == 2
    assert summary["model_usage"]["embedding_successful_calls"] == 0
    assert summary["model_usage"]["embedding_placeholder_calls"] == 2
    assert summary["model_usage"]["embedding_failed_calls"] == 0
    assert summary["model_usage"]["embedding_provider_models"] == {"placeholder:local-placeholder": 2}
    assert summary["model_usage"]["embedding_dimensions"] == {"4": 2}
    assert (output_dir / "eval-summary.json").exists()
    assert (output_dir / "eval-results.jsonl").exists()
    assert (output_dir / "eval-confusion-matrix.json").exists()
    assert (output_dir / "eval-confusion-matrix.csv").exists()
    assert (output_dir / "eval-failures.jsonl").exists()
    assert (output_dir / "eval-model-usage.jsonl").exists()

    results = [json.loads(line) for line in (output_dir / "eval-results.jsonl").read_text(encoding="utf-8").splitlines()]
    failures = [json.loads(line) for line in (output_dir / "eval-failures.jsonl").read_text(encoding="utf-8").splitlines()]
    model_usage = [json.loads(line) for line in (output_dir / "eval-model-usage.jsonl").read_text(encoding="utf-8").splitlines()]

    assert sorted(row["primary_correct"] for row in results) == [False, True]
    assert {row["confidence_bucket"] for row in results} == {"high"}
    assert {row["ocr_fallback_used"] for row in results} == {False}
    assert {row["llm_structured_output_valid"] for row in results} == {True}
    assert failures[0]["correct_primary_tag"] == "history_archive_general"
    assert {row["golden_label_id"] for row in model_usage} == {1, 2}
    assert (output_dir / "graph-runs" / "00001" / "graph-result.json").exists()


def test_golden_pipeline_evaluation_records_missing_files(tmp_path: Path) -> None:
    labels_db = tmp_path / "labels.sqlite"
    with sqlite3.connect(labels_db) as connection:
        connection.executescript(
            """
            create table golden_labels (
                id integer primary key autoincrement,
                source_path text not null unique,
                relative_path text not null,
                sample_path text,
                correct_primary_tag text not null,
                correct_secondary_tags_json text not null default '[]',
                updated_at text not null default (datetime('now'))
            );
            """
        )
        connection.execute(
            """
            insert into golden_labels (
                source_path, relative_path, sample_path, correct_primary_tag, correct_secondary_tags_json
            ) values (?, ?, ?, ?, ?)
            """,
            ("/missing/file.pdf", "missing/file.pdf", str(tmp_path / "missing.pdf"), "meeting_records", '["minutes"]'),
        )

    output_dir = tmp_path / "eval-out"
    summary = run_golden_pipeline_evaluation(labels_db, output_dir=output_dir, semantic_index_path=None)

    assert summary["missing_files"] == 1
    assert summary["failure_count"] == 1
    assert summary["primary_accuracy"] == 0.0
    assert summary["acceptance_gate"]["status"] == "fail"
    results = [json.loads(line) for line in (output_dir / "eval-results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert results[0]["review_reason"] == "file_missing"
    assert results[0]["failure_reasons"] == ["missing_file", "primary_tag_mismatch"]
