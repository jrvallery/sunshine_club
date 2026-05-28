from __future__ import annotations

import json
from pathlib import Path

from sunshine_extraction.evals.provider_benchmark import benchmark_extraction_providers
from sunshine_extraction.services.evaluation import benchmark_extraction_providers as benchmark_extraction_providers_service


def test_provider_benchmark_runs_current_provider_and_writes_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "minutes.txt"
    source.write_text("Meeting minutes and Sunshine Club notes.", encoding="utf-8")
    output_dir = tmp_path / "benchmark"

    result = benchmark_extraction_providers([source], provider_names=["current"], output_dir=output_dir)

    assert result["summary"]["result_count"] == 1
    assert result["summary"]["by_provider"]["current"] == 1
    assert result["summary"]["provider_availability"]["current"]["available"] is True
    assert result["summary"]["local_only"] is True
    assert result["summary"]["comparison"]["paired_file_count"] == 0
    assert result["summary"]["recommendations"][0]["provider"] == "current"
    assert result["summary"]["recommendations"][0]["promotion_status"] == "candidate"
    assert result["recommendations"][0]["ok_quality_rate"] == 1.0
    assert result["results"][0]["status"] == "extracted"
    assert result["results"][0]["quality"] == "ok"
    rows = [json.loads(line) for line in (output_dir / "provider-benchmark-results.jsonl").read_text(encoding="utf-8").splitlines()]
    parser_rows = [json.loads(line) for line in (output_dir / "sample-parser-results.jsonl").read_text(encoding="utf-8").splitlines()]
    recommendations = [json.loads(line) for line in (output_dir / "provider-benchmark-recommendations.jsonl").read_text(encoding="utf-8").splitlines()]
    summary = json.loads((output_dir / "provider-benchmark-summary.json").read_text(encoding="utf-8"))
    assert rows[0]["provider"] == "current"
    assert parser_rows[0]["parser_provider"] == "current"
    assert parser_rows[0]["status"] == "extracted"
    assert parser_rows[0]["quality"] == "ok"
    assert parser_rows[0]["text_snippet"] == "Meeting minutes and Sunshine Club notes."
    assert recommendations[0]["promotion_status"] == "candidate"
    assert summary["result_count"] == 1


def test_provider_benchmark_supports_optional_local_parser_boundaries(tmp_path: Path) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"fake pdf")

    result = benchmark_extraction_providers_service(
        [source],
        provider_names=["mineru", "ragflow_deepdoc", "unstructured"],
    )

    assert result["summary"]["result_count"] == 3
    assert result["summary"]["local_only"] is True
    assert result["summary"]["by_provider"] == {
        "mineru": 1,
        "ragflow_deepdoc": 1,
        "unstructured": 1,
    }
    assert result["summary"]["provider_availability"]["mineru"]["local_only"] is True
    assert {row["status"] for row in result["results"]} == {"skipped"}
    assert {row["promotion_status"] for row in result["recommendations"]} == {"blocked_dependency_unavailable"}


def test_provider_benchmark_loads_canonical_sample_manifest(tmp_path: Path) -> None:
    source = tmp_path / "minutes.txt"
    source.write_text("Meeting minutes and Sunshine Club notes.", encoding="utf-8")
    manifest = tmp_path / "provider-benchmark-samples.json"
    manifest.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "path": "minutes.txt",
                        "category": "born_digital_text",
                        "label": "meeting minutes text fixture",
                        "metadata": {"risk": "low"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = benchmark_extraction_providers([], provider_names=["current"], sample_manifest=manifest)

    assert result["summary"]["sample_count"] == 1
    assert result["summary"]["sample_manifest"] == str(manifest)
    assert result["summary"]["sample_categories"] == {"born_digital_text": 1}
    assert result["results"][0]["sample_category"] == "born_digital_text"
    assert result["results"][0]["sample_label"] == "meeting minutes text fixture"
    assert result["parser_results"][0]["sample_category"] == "born_digital_text"
    assert result["parser_results"][0]["metadata"]["sample_metadata"] == {"risk": "low"}
