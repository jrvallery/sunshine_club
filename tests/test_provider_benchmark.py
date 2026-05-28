from __future__ import annotations

import json
from pathlib import Path

from sunshine_extraction.evals.provider_benchmark import benchmark_extraction_providers


def test_provider_benchmark_runs_current_provider_and_writes_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "minutes.txt"
    source.write_text("Meeting minutes and Sunshine Club notes.", encoding="utf-8")
    output_dir = tmp_path / "benchmark"

    result = benchmark_extraction_providers([source], provider_names=["current"], output_dir=output_dir)

    assert result["summary"]["result_count"] == 1
    assert result["summary"]["by_provider"]["current"] == 1
    assert result["summary"]["local_only"] is True
    assert result["results"][0]["status"] == "extracted"
    assert result["results"][0]["quality"] == "ok"
    rows = [json.loads(line) for line in (output_dir / "provider-benchmark-results.jsonl").read_text(encoding="utf-8").splitlines()]
    summary = json.loads((output_dir / "provider-benchmark-summary.json").read_text(encoding="utf-8"))
    assert rows[0]["provider"] == "current"
    assert summary["result_count"] == 1
