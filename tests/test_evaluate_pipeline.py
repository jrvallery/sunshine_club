from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from sunshine_extraction.embeddings import PlaceholderEmbeddingProvider
from sunshine_extraction.evaluate_pipeline import (
    GoldenEvalLabel,
    _evaluation_row,
    _model_usage_failure_reasons,
    _parse_args,
    _per_file_model_usage_summary,
    _resolve_eval_embedding_provider,
    _resolve_eval_ocr_executor,
    _update_totals,
    run_golden_pipeline_evaluation,
)
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
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
        }


def test_pipeline_eval_cli_accepts_documented_golden_labels_alias(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_pipeline",
            "--golden-labels",
            "/tmp/labels.sqlite",
            "--embedding-provider",
            "placeholder",
            "--ocr-fallback-provider",
            "cortex",
        ],
    )
    args = _parse_args()
    assert args.labels_db == "/tmp/labels.sqlite"
    assert args.embedding_provider == "placeholder"
    assert args.ocr_fallback_provider == "cortex"


def test_eval_row_requires_uncertainty_evidence_for_medium_confidence(tmp_path: Path) -> None:
    label = GoldenEvalLabel(
        id=1,
        source_path="/source/history.pdf",
        relative_path="history.pdf",
        sample_path=None,
        correct_primary_tag="history_archive_general",
        correct_secondary_tags=[],
        content_class="document",
        ocr_quality_label="ok",
        expected_review_required=False,
        sensitive_record=False,
        correct_destination_path=None,
        correct_placement_year=None,
        correct_privacy=None,
        reviewer="tester",
        reviewed_at="2026-05-27T00:00:00Z",
        notes=None,
    )
    base_result = {
        "top_tag_candidate": "history_archive_general",
        "secondary_tags": [],
        "final_class": "document",
        "quality": "ok",
        "route_status": "route_candidate",
        "tag_confidence": 0.72,
        "tag_evidence": ["matched history"],
    }

    unexplained = _evaluation_row(label, base_result, tmp_path)
    explained = _evaluation_row(
        label,
        {
            **base_result,
            "confidence_calibration": {
                "factors": ["semantic_examples_weak"],
                "review_reason": "medium confidence because retrieved examples were weak",
            },
        },
        tmp_path,
    )

    assert unexplained["confidence_bucket"] == "medium"
    assert unexplained["medium_confidence_uncertainty_explained"] is False
    assert "medium_confidence_unexplained" in unexplained["failure_reasons"]
    assert explained["medium_confidence_uncertainty_explained"] is True
    assert "medium_confidence_unexplained" not in explained["failure_reasons"]
    assert explained["confidence_calibration_factors"] == ["semantic_examples_weak"]


def test_eval_row_marks_resolved_placement_unsafe_when_route_requires_review(tmp_path: Path) -> None:
    label = GoldenEvalLabel(
        id=1,
        source_path="/source/history.pdf",
        relative_path="history.pdf",
        sample_path=None,
        correct_primary_tag="history_archive_general",
        correct_secondary_tags=[],
        content_class="document",
        ocr_quality_label="ok",
        expected_review_required=True,
        sensitive_record=False,
        correct_destination_path=None,
        correct_placement_year=None,
        correct_privacy=None,
        reviewer="tester",
        reviewed_at="2026-05-27T00:00:00Z",
        notes=None,
    )
    row = _evaluation_row(
        label,
        {
            "top_tag_candidate": "history_archive_general",
            "final_class": "document",
            "quality": "ok",
            "route_status": "review_low_confidence_tag",
            "review_reason": "tag_confidence_below_threshold",
            "tag_confidence": 0.62,
            "tag_evidence": ["matched history"],
            "placement_status": "resolved",
            "destination_path": "06_History_Archive/1992",
        },
        tmp_path,
    )

    assert row["predicted_review_required"] is True
    assert row["unsafe_placement_proposal"] is True
    assert "unsafe_placement_proposal" in row["failure_reasons"]


def test_eval_row_groups_deferred_extraction_as_failure(tmp_path: Path) -> None:
    label = GoldenEvalLabel(
        id=1,
        source_path="/source/publisher.pub",
        relative_path="publisher.pub",
        sample_path=None,
        correct_primary_tag="communications_templates",
        correct_secondary_tags=[],
        content_class="deferred_technical",
        ocr_quality_label="deferred",
        expected_review_required=True,
        sensitive_record=False,
        correct_destination_path=None,
        correct_placement_year=None,
        correct_privacy=None,
        reviewer="tester",
        reviewed_at="2026-05-27T00:00:00Z",
        notes=None,
    )

    row = _evaluation_row(
        label,
        {
            "top_tag_candidate": "communications_templates",
            "final_class": "deferred_technical",
            "quality": "deferred",
            "extraction_status": "deferred_technical",
            "route_status": "review_or_extraction_deferred",
            "review_reason": "extractor_deferred",
            "tag_confidence": 0.3,
            "tag_evidence": ["deferred technical file"],
        },
        tmp_path,
    )

    assert row["primary_correct"] is True
    assert row["predicted_review_required"] is True
    assert "extraction_deferred" in row["failure_reasons"]


def test_eval_row_groups_invalid_llm_structured_output_as_failure(tmp_path: Path) -> None:
    label = GoldenEvalLabel(
        id=1,
        source_path="/source/tea.pdf",
        relative_path="tea.pdf",
        sample_path=None,
        correct_primary_tag="annual_spring_tea",
        correct_secondary_tags=[],
        content_class="document",
        ocr_quality_label="ok",
        expected_review_required=True,
        sensitive_record=False,
        correct_destination_path=None,
        correct_placement_year=None,
        correct_privacy=None,
        reviewer="tester",
        reviewed_at="2026-05-27T00:00:00Z",
        notes=None,
    )

    row = _evaluation_row(
        label,
        {
            "top_tag_candidate": "annual_spring_tea",
            "final_class": "document",
            "quality": "ok",
            "route_status": "review_tag_confidence_calibration",
            "review_reason": "llm_structured_output_invalid",
            "tag_confidence": 0.79,
            "tag_evidence": ["matched tea"],
            "llm_status": "inspected_with_invalid_fields",
            "warnings": ["llm_invalid_secondary_tags:not_a_real_tag"],
        },
        tmp_path,
    )

    assert row["primary_correct"] is True
    assert row["llm_structured_output_valid"] is False
    assert row["review_routing_correct"] is True
    assert "llm_structured_output_invalid" in row["failure_reasons"]


def test_eval_row_groups_ocr_fallback_failures_by_cause(tmp_path: Path) -> None:
    label = GoldenEvalLabel(
        id=1,
        source_path="/source/guest-list.pdf",
        relative_path="guest-list.pdf",
        sample_path=None,
        correct_primary_tag="annual_spring_tea",
        correct_secondary_tags=[],
        content_class="scanned_document",
        ocr_quality_label="ok",
        expected_review_required=True,
        sensitive_record=False,
        correct_destination_path=None,
        correct_placement_year=None,
        correct_privacy=None,
        reviewer="tester",
        reviewed_at="2026-05-27T00:00:00Z",
        notes=None,
    )

    row = _evaluation_row(
        label,
        {
            "top_tag_candidate": "annual_spring_tea",
            "final_class": "scanned_document",
            "quality": "poor",
            "route_status": "review_ocr_quality",
            "review_reason": "ocr_quality_not_trusted",
            "tag_confidence": 0.58,
            "tag_evidence": ["matched tea"],
            "warnings": ["ocr_fallback_failed:TimeoutError"],
        },
        tmp_path,
    )

    totals = Counter()
    _update_totals(totals, row, label)

    assert row["ocr_fallback_used"] is False
    assert row["ocr_fallback_failed"] is True
    assert "ocr_fallback_failed" in row["failure_reasons"]
    assert "ocr_quality_mismatch" in row["failure_reasons"]
    assert totals["ocr_fallback_failed"] == 1


def test_per_file_model_usage_summary_flags_untracked_external_costs() -> None:
    summary = _per_file_model_usage_summary(
        [
            {
                "purpose": "tag_inspection",
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "status": "ok",
                "cost_basis": "external",
                "runtime_ms": 1200,
                "total_tokens": 250,
                "estimated_cost_usd": None,
            },
            {
                "purpose": "chunk_embedding",
                "provider": "unknown",
                "model": "unknown",
                "status": "unknown",
                "cost_basis": "unknown",
                "runtime_ms": None,
            },
        ]
    )

    assert summary["total_calls"] == 2
    assert summary["external_calls"] == 1
    assert summary["unknown_cost_basis_count"] == 1
    assert summary["unknown_external_cost_calls"] == 1
    assert summary["missing_required_field_counts"] == {
        "cost_basis": 1,
        "model": 1,
        "provider": 1,
        "runtime_ms": 1,
        "status": 1,
    }
    assert _model_usage_failure_reasons(summary) == [
        "model_usage_missing_required_fields",
        "model_usage_unknown_cost_basis",
        "model_usage_external_cost_untracked",
    ]


def test_eval_embedding_provider_resolution_records_configuration_fallback(monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_EMBEDDING_PROVIDER", "not-a-provider")

    provider, warnings = _resolve_eval_embedding_provider(None)

    assert isinstance(provider, PlaceholderEmbeddingProvider)
    assert warnings
    assert warnings[0].startswith("embedding_provider_configuration_failed:")


def test_eval_embedding_provider_resolution_uses_provider_override(monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_EMBEDDING_PROVIDER", "not-a-provider")

    provider, warnings = _resolve_eval_embedding_provider(None, provider_name_override="placeholder")

    assert isinstance(provider, PlaceholderEmbeddingProvider)
    assert warnings == []


def test_eval_ocr_resolution_records_fallback_configuration_failure(monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_OCR_FALLBACK_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API", raising=False)

    executor, warnings = _resolve_eval_ocr_executor(None)

    assert executor.engine_name == "tesseract"
    assert warnings == ["ocr_fallback_configuration_failed:openai"]


def test_sensitive_false_accept_counts_even_when_primary_tag_is_correct(tmp_path: Path) -> None:
    label = GoldenEvalLabel(
        id=1,
        source_path="/source/member-roster.pdf",
        relative_path="member-roster.pdf",
        sample_path=None,
        correct_primary_tag="membership_rosters_yearbooks",
        correct_secondary_tags=[],
        content_class="document",
        ocr_quality_label="ok",
        expected_review_required=True,
        sensitive_record=True,
        correct_destination_path=None,
        correct_placement_year=None,
        correct_privacy=None,
        reviewer="tester",
        reviewed_at="2026-05-27T00:00:00Z",
        notes=None,
    )
    row = _evaluation_row(
        label,
        {
            "top_tag_candidate": "membership_rosters_yearbooks",
            "final_class": "document",
            "quality": "ok",
            "route_status": "route_candidate",
            "tag_confidence": 0.96,
            "tag_evidence": ["roster evidence"],
        },
        tmp_path,
    )
    totals = Counter()

    _update_totals(totals, row, label)

    assert row["primary_correct"] is True
    assert row["predicted_review_required"] is False
    assert "sensitive_false_accept" in row["failure_reasons"]
    assert totals["review_false_negative"] == 1
    assert totals["sensitive_false_accepts"] == 1


def test_golden_pipeline_evaluation_runs_graph_and_writes_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUNSHINE_OCR_FALLBACK_PROVIDER", "disabled")
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
    assert summary["ocr_acceptable_rate"] == 1.0
    assert summary["ocr_fallback_rate"] == 0.0
    assert summary["ocr_fallback_failed_count"] == 0
    assert summary["review_routing_precision"] == 0.5
    assert summary["review_routing_recall"] == 1.0
    assert summary["review_false_accepts"] == 0
    assert summary["review_false_reviews"] == 1
    assert summary["sensitive_medium_low_confidence_accepts"] == 0
    assert summary["llm_structured_output_validity_rate"] == 1.0
    assert summary["placement_destination_accuracy"] == 0.5
    assert summary["unsafe_placement_proposal_count"] == 0
    assert summary["privacy_accuracy"] == 0.5
    assert summary["secondary_precision"] == 0.5
    assert summary["secondary_recall"] == 0.5
    assert summary["failure_count"] == 2
    assert summary["embedding_success_rate"] == 0.0
    assert summary["semantic_same_family_top5_rate"] == 0.0
    assert summary["high_risk_primary_accuracy_min"] is None
    assert summary["high_confidence_primary_accuracy"] == 0.5
    assert summary["high_confidence_false_accepts"] == 0
    assert summary["low_confidence_false_accepts"] == 0
    assert summary["low_confidence_accepted_count"] == 0
    assert summary["medium_confidence_unexplained_count"] == 0
    assert summary["invalid_primary_tag_count"] == 0
    assert summary["tag_evidence_presence_rate"] == 1.0
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
    assert summary["primary_tag_metrics"]["annual_spring_tea"]["accepted"] == 0
    assert summary["primary_tag_metrics"]["annual_spring_tea"]["false_accepts"] == 0
    assert summary["primary_tag_metrics"]["annual_spring_tea"]["false_reviews"] == 1
    assert summary["primary_tag_metrics"]["annual_spring_tea"]["secondary_precision"] == 1.0
    assert summary["primary_tag_metrics"]["annual_spring_tea"]["secondary_recall"] == 1.0
    assert summary["primary_tag_metrics"]["history_archive_general"]["accuracy"] == 0.0
    assert summary["primary_tag_metrics"]["history_archive_general"]["accepted"] == 0
    assert summary["primary_tag_metrics"]["history_archive_general"]["false_accepts"] == 0
    assert summary["primary_tag_metrics"]["history_archive_general"]["false_reviews"] == 0
    assert summary["primary_tag_metrics"]["history_archive_general"]["secondary_precision"] == 0.0
    assert summary["primary_tag_metrics"]["history_archive_general"]["secondary_recall"] == 0.0
    assert summary["confidence_bucket_metrics"]["high"]["total"] == 2
    assert summary["confidence_bucket_metrics"]["high"]["accepted"] == 0
    assert summary["confidence_bucket_metrics"]["high"]["primary_accuracy"] == 0.5
    assert summary["confidence_bucket_metrics"]["high"]["false_reviews"] == 1
    assert summary["acceptance_gate"]["status"] == "fail"
    assert {check["name"] for check in summary["acceptance_gate"]["blocking_checks"]} == {
        "embedding_placeholder_calls",
        "golden_label_count",
        "high_risk_label_min_count",
        "high_risk_primary_accuracy",
        "high_confidence_primary_accuracy",
        "primary_taxonomy_coverage",
        "primary_accuracy",
        "placement_destination_accuracy",
        "placement_year_accuracy",
        "privacy_accuracy",
        "semantic_same_family_top5_rate",
    }
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "source_file_mutations")["status"] == "pass"
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "ocr_acceptable_rate")["status"] == "pass"
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "llm_structured_output_validity_rate")["status"] == "pass"
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "invalid_primary_tag_count")["status"] == "pass"
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "tag_evidence_presence_rate")["status"] == "pass"
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "placement_year_accuracy")["status"] == "not_evaluated"
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "unsafe_placement_proposal_count")["status"] == "pass"
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "low_confidence_false_accepts")["status"] == "pass"
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "low_confidence_accepted_count")["status"] == "pass"
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "medium_confidence_unexplained_count")["status"] == "pass"
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "sensitive_medium_low_confidence_accepts")["status"] == "pass"
    assert summary["production_readiness"]["status"] == "not_ready"
    assert summary["production_readiness"]["larger_batch_allowed"] is False
    assert summary["production_readiness"]["customer_claims_allowed"] is False
    assert "embedding_placeholder_calls" in summary["production_readiness"]["blocking_reasons"]
    assert summary["production_readiness"]["status_counts"] == {
        "accepted": 0,
        "review_required": 2,
        "failed": 0,
        "deferred": 0,
    }
    assert summary["production_readiness"]["reliable_categories"] == []
    assert {item["tag"] for item in summary["production_readiness"]["underrepresented_categories"]} == {
        "annual_spring_tea",
        "history_archive_general",
    }
    assert any("golden QA set" in action for action in summary["production_readiness"]["required_next_actions"])
    assert any("real embedding provider" in action for action in summary["production_readiness"]["required_next_actions"])
    assert any("Calibrate confidence" in action for action in summary["production_readiness"]["required_next_actions"])
    assert any("same-family labels" in action for action in summary["production_readiness"]["required_next_actions"])
    assert summary["run_metadata"]["embedding_provider"] == "placeholder"
    assert summary["run_metadata"]["embedding_model"] == "local-placeholder"
    assert summary["run_metadata"]["embedding_dimensions"] == 4
    assert summary["run_metadata"]["ocr_mode"] == "tesseract"
    assert summary["run_metadata"]["ocr_primary_engine"] == "tesseract"
    assert summary["run_metadata"]["ocr_fallback_mode"] == "disabled"
    assert summary["run_metadata"]["ocr_fallback_model"] is None
    assert summary["run_metadata"]["warnings"] == []
    assert summary["run_warnings"] == []
    assert summary["by_failure_reason"] == {
        "embedding_quality_unavailable": 2,
        "placement_destination_mismatch": 1,
        "primary_tag_mismatch": 1,
        "privacy_mismatch": 1,
        "review_routing_mismatch": 1,
        "semantic_retrieval_missing": 1,
    }
    assert summary["failure_groups"][0]["reason"] == "embedding_quality_unavailable"
    assert summary["failure_groups"][0]["count"] == 2
    assert summary["failure_groups"][0]["affected_primary_tags"] == {
        "annual_spring_tea": 1,
        "history_archive_general": 1,
    }
    assert any(group["reason"] == "primary_tag_mismatch" for group in summary["failure_groups"])
    assert summary["model_usage"]["by_purpose"] == {
        "chunk_embedding": 2,
        "semantic_retrieval_embedding": 0,
        "tag_inspection": 2,
    }
    assert summary["model_usage"]["local_call_count"] == 2
    assert summary["model_usage"]["external_call_count"] == 0
    assert summary["model_usage"]["placeholder_call_count"] == 2
    assert summary["model_usage"]["by_cost_basis"] == {"local": 2, "placeholder": 2}
    assert summary["model_usage"]["unknown_cost_basis_count"] == 0
    assert summary["model_usage"]["embedding_attempted_calls"] == 2
    assert summary["model_usage"]["embedding_successful_calls"] == 0
    assert summary["model_usage"]["embedding_placeholder_calls"] == 2
    assert summary["model_usage"]["embedding_failed_calls"] == 0
    assert summary["model_usage"]["embedding_provider_models"] == {"placeholder:local-placeholder": 2}
    assert summary["model_usage"]["embedding_dimensions"] == {"4": 2}
    assert summary["model_usage"]["required_field_completeness_rate"] == 1.0
    assert summary["model_usage"]["cost_basis_completeness_rate"] == 1.0
    assert summary["model_usage"]["missing_required_field_counts"] == {}
    assert summary["model_usage"]["input_tokens"] == 200
    assert summary["model_usage"]["output_tokens"] == 40
    assert summary["model_usage"]["total_tokens"] == 240
    assert summary["model_usage"]["estimated_external_cost_usd"] == 0.0
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "model_usage_required_fields_tracked")["status"] == "pass"
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "model_usage_cost_basis_tracked")["status"] == "pass"
    assert (output_dir / "eval-summary.json").exists()
    assert (output_dir / "eval-results.jsonl").exists()
    assert (output_dir / "eval-confusion-matrix.json").exists()
    assert (output_dir / "eval-confusion-matrix.csv").exists()
    assert (output_dir / "eval-failures.jsonl").exists()
    assert (output_dir / "eval-failure-groups.json").exists()
    assert (output_dir / "eval-model-usage.jsonl").exists()
    assert (output_dir / "eval-artifacts-manifest.json").exists()
    assert summary["artifacts"]["artifact_manifest"] == str(output_dir / "eval-artifacts-manifest.json")

    results = [json.loads(line) for line in (output_dir / "eval-results.jsonl").read_text(encoding="utf-8").splitlines()]
    failures = [json.loads(line) for line in (output_dir / "eval-failures.jsonl").read_text(encoding="utf-8").splitlines()]
    failure_groups = json.loads((output_dir / "eval-failure-groups.json").read_text(encoding="utf-8"))
    artifact_manifest = json.loads((output_dir / "eval-artifacts-manifest.json").read_text(encoding="utf-8"))
    model_usage = [json.loads(line) for line in (output_dir / "eval-model-usage.jsonl").read_text(encoding="utf-8").splitlines()]

    manifest_by_name = {row["name"]: row for row in artifact_manifest["artifacts"]}
    assert artifact_manifest["artifact_count"] == 6
    assert manifest_by_name["summary"]["exists"] is True
    assert manifest_by_name["summary"]["size_bytes"] > 0
    assert len(manifest_by_name["summary"]["sha256"]) == 64
    assert manifest_by_name["failure_groups"]["exists"] is True
    assert sorted(row["primary_correct"] for row in results) == [False, True]
    assert {row["source_file_mutation"]["mutated"] for row in results} == {False}
    assert all(len(row["source_file_mutation"]["before"]["sha256"]) == 64 for row in results)
    assert all(row["source_file_mutation"]["before"]["sha256"] == row["source_file_mutation"]["after"]["sha256"] for row in results)
    assert {row["confidence_bucket"] for row in results} == {"high"}
    assert {row["ocr_fallback_used"] for row in results} == {False}
    assert {row["ocr_fallback_failed"] for row in results} == {False}
    assert {row["model_usage_summary"]["total_calls"] for row in results} == {2}
    assert {row["model_usage_summary"]["total_model_usage_rows"] for row in results} == {3}
    assert {row["llm_structured_output_valid"] for row in results} == {True}
    assert all(row["tag_evidence"] for row in results)
    assert failures[0]["correct_primary_tag"] == "history_archive_general"
    assert failure_groups[0]["reason"] == "embedding_quality_unavailable"
    assert failure_groups[0]["examples"][0]["relative_path"]
    assert {row["golden_label_id"] for row in model_usage} == {1, 2}
    assert {row["total_tokens"] for row in model_usage if row["purpose"] == "tag_inspection"} == {120}
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
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "high_confidence_primary_accuracy")["status"] == "not_evaluated"
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "ocr_acceptable_rate")["status"] == "not_evaluated"
    assert next(check for check in summary["acceptance_gate"]["checks"] if check["name"] == "llm_structured_output_validity_rate")["status"] == "not_evaluated"
    assert summary["production_readiness"]["larger_batch_allowed"] is False
    assert summary["production_status_counts"]["failed"] == 1
    assert summary["production_status_counts"]["review_required"] == 0
    results = [json.loads(line) for line in (output_dir / "eval-results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert results[0]["review_reason"] == "file_missing"
    assert results[0]["failure_reasons"] == ["missing_file", "primary_tag_mismatch"]
