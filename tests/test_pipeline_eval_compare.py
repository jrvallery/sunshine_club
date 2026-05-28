from __future__ import annotations

from sunshine_api.routers.semantic import _pipeline_eval_comparison


def test_pipeline_eval_comparison_tracks_changed_failure_reasons() -> None:
    baseline = {"id": 1, "summary": {"primary_accuracy": 0.5}}
    current = {"id": 2, "summary": {"primary_accuracy": 0.5}}
    baseline_results = {
        "/source/a.pdf": {
            "source_path": "/source/a.pdf",
            "relative_path": "a.pdf",
            "correct_primary_tag": "annual_spring_tea",
            "predicted_primary_tag": "annual_spring_tea",
            "predicted_secondary_tags": [],
            "route_status": "review_ocr_quality",
            "failure_reasons": ["ocr_quality_mismatch"],
        }
    }
    current_results = {
        "/source/a.pdf": {
            "source_path": "/source/a.pdf",
            "relative_path": "a.pdf",
            "correct_primary_tag": "annual_spring_tea",
            "predicted_primary_tag": "annual_spring_tea",
            "predicted_secondary_tags": [],
            "route_status": "review_ocr_quality",
            "failure_reasons": ["ocr_fallback_failed"],
        }
    }

    comparison = _pipeline_eval_comparison(baseline, current, baseline_results, current_results)

    assert comparison["changed_prediction_count"] == 0
    assert comparison["fixed_failure_count"] == 0
    assert comparison["regressed_failure_count"] == 0
    assert comparison["changed_failure_reason_count"] == 1
    assert comparison["changed_failure_reasons"][0]["baseline_failure_reasons"] == ["ocr_quality_mismatch"]
    assert comparison["changed_failure_reasons"][0]["current_failure_reasons"] == ["ocr_fallback_failed"]
