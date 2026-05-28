"""Local extraction provider benchmark runner."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from sunshine_extraction.providers.extraction import (
    CurrentExtractionProvider,
    DoclingExtractionProvider,
    ExtractionProvider,
    MinerUExtractionProvider,
    RAGFlowDeepDocExtractionProvider,
    UnstructuredExtractionProvider,
)
from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import OcrArtifacts, ocr_executor_from_env, extraction_quality_gate
from sunshine_extraction.evals.provider_benchmark_samples import load_provider_benchmark_samples


def benchmark_extraction_providers(
    input_paths: list[str | Path] | None = None,
    *,
    provider_names: list[str] | None = None,
    output_dir: str | Path | None = None,
    sample_manifest: str | Path | None = None,
    sample_root: str | Path | None = None,
    sample_categories: list[str] | None = None,
    sample_limit: int | None = None,
    max_average_seconds: float | None = 30.0,
    _provider_instances: list[ExtractionProvider] | None = None,
) -> dict[str, Any]:
    samples = _filter_samples(
        _benchmark_samples(input_paths or [], sample_manifest=sample_manifest, sample_root=sample_root),
        sample_categories=sample_categories,
        sample_limit=sample_limit,
    )
    providers = _provider_instances or _providers(provider_names)
    output_path = Path(output_dir) if output_dir is not None else None
    if output_path is not None:
        output_path.mkdir(parents=True, exist_ok=True)
        _reset_incremental_artifacts(output_path)
    rows: list[dict[str, Any]] = []
    parser_rows: list[dict[str, Any]] = []
    for index, sample_spec in enumerate(samples, start=1):
        sample = _sample(Path(sample_spec["path"]), index, sample_spec=sample_spec)
        plan = _default_plan(sample)
        for provider in providers:
            row, parser_row = _benchmark_one(sample, plan, provider, sample_spec=sample_spec)
            rows.append(row)
            parser_rows.append(parser_row)
            if output_path is not None:
                _append_jsonl(output_path / "provider-benchmark-results.jsonl", row)
                _append_jsonl(output_path / "sample-parser-results.jsonl", parser_row)
    summary = _summary(rows)
    summary["sample_count"] = len(samples)
    summary["sample_manifest"] = str(sample_manifest) if sample_manifest else None
    summary["sample_categories"] = _count(rows, "sample_category")
    summary["sample_filter"] = {
        "categories": sorted({category.strip() for category in sample_categories or [] if category.strip()}),
        "limit": sample_limit,
    }
    summary["runtime_policy"] = {"max_average_seconds": max_average_seconds}
    recommendations = _provider_recommendations(rows, max_average_seconds=max_average_seconds)
    summary["recommendations"] = recommendations
    if output_path is not None:
        _write_jsonl(output_path / "provider-benchmark-recommendations.jsonl", recommendations)
        (output_path / "provider-benchmark-summary.json").write_text(_json_dumps(summary), encoding="utf-8")
    return {"summary": summary, "results": rows, "parser_results": parser_rows, "recommendations": recommendations}


def _benchmark_one(sample: SampleFile, plan: dict[str, Any], provider: ExtractionProvider, *, sample_spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    try:
        status = provider.dependency_status()
    except Exception as error:
        status = _failed_dependency_status(provider, error)
    ocr_artifacts = OcrArtifacts(pages=[], documents=[])
    try:
        extraction, attempt = provider.extract(sample, plan, ocr_executor=ocr_executor_from_env(), ocr_artifacts=ocr_artifacts)
    except Exception as error:
        return _failed_provider_rows(
            sample=sample,
            plan=plan,
            sample_spec=sample_spec,
            provider=provider,
            provider_status=status,
            error=error,
            seconds=round(time.perf_counter() - started, 4),
        )
    quality = extraction_quality_gate(extraction)
    benchmark_row = {
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
        "sample_path": str(sample.sample_path),
        "sample_category": sample_spec.get("category") or "uncategorized",
        "sample_label": sample_spec.get("label") or sample.sample_path.name,
        "provider": attempt.provider,
        "provider_available": bool(status.get("available", True)),
        "local_only": bool(status.get("local_only", True)),
        "strategy": plan.get("strategy"),
        "status": attempt.status,
        "quality": quality.get("quality"),
        "can_chunk": quality.get("can_chunk"),
        "requires_review": quality.get("requires_review"),
        "text_length": len(extraction.text or ""),
        "page_count": extraction.page_count,
        "seconds": attempt.seconds,
        "warnings": [*attempt.warnings, *extraction.warnings],
        "dependency_status": status,
        "metadata": attempt.metadata,
    }
    parser_row = _parser_result_row(
        sample=sample,
        plan=plan,
        sample_spec=sample_spec,
        provider_status=status,
        extraction_status=extraction.extraction_status,
        extraction_text=extraction.text or "",
        extraction_metadata=extraction.metadata,
        extraction_page_count=extraction.page_count,
        attempt=attempt.as_row(),
        quality=quality,
        warnings=benchmark_row["warnings"],
    )
    return benchmark_row, parser_row


def _failed_dependency_status(provider: ExtractionProvider, error: Exception) -> dict[str, Any]:
    return {
        "provider": getattr(provider, "provider_name", provider.__class__.__name__),
        "available": False,
        "local_only": True,
        "error_type": error.__class__.__name__,
        "error": str(error),
    }


def _failed_provider_rows(
    *,
    sample: SampleFile,
    plan: dict[str, Any],
    sample_spec: dict[str, Any],
    provider: ExtractionProvider,
    provider_status: dict[str, Any],
    error: Exception,
    seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    provider_name = str(provider_status.get("provider") or getattr(provider, "provider_name", provider.__class__.__name__))
    warnings = [f"provider_exception:{error.__class__.__name__}"]
    attempt = {
        "provider": provider_name,
        "status": "failed",
        "strategy": plan.get("strategy"),
        "seconds": seconds,
        "warnings": warnings,
        "metadata": {
            "error_type": error.__class__.__name__,
            "error": str(error),
            "local_only": bool(provider_status.get("local_only", True)),
        },
    }
    quality = {
        "quality": "failed",
        "can_chunk": False,
        "requires_review": True,
        "reason": "provider_exception",
    }
    benchmark_row = {
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
        "sample_path": str(sample.sample_path),
        "sample_category": sample_spec.get("category") or "uncategorized",
        "sample_label": sample_spec.get("label") or sample.sample_path.name,
        "provider": provider_name,
        "provider_available": bool(provider_status.get("available", False)),
        "local_only": bool(provider_status.get("local_only", True)),
        "strategy": plan.get("strategy"),
        "status": "failed",
        "quality": "failed",
        "can_chunk": False,
        "requires_review": True,
        "text_length": 0,
        "page_count": None,
        "seconds": seconds,
        "warnings": warnings,
        "dependency_status": provider_status,
        "metadata": attempt["metadata"],
    }
    parser_row = _parser_result_row(
        sample=sample,
        plan=plan,
        sample_spec=sample_spec,
        provider_status=provider_status,
        extraction_status="failed",
        extraction_text="",
        extraction_metadata={"provider": provider_name, "error_type": error.__class__.__name__, "error": str(error)},
        extraction_page_count=None,
        attempt=attempt,
        quality=quality,
        warnings=warnings,
    )
    return benchmark_row, parser_row


def _parser_result_row(
    *,
    sample: SampleFile,
    plan: dict[str, Any],
    sample_spec: dict[str, Any],
    provider_status: dict[str, Any],
    extraction_status: str,
    extraction_text: str,
    extraction_metadata: dict[str, Any],
    extraction_page_count: int | None,
    attempt: dict[str, Any],
    quality: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    provider = str(attempt.get("provider") or "unknown")
    return {
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
        "sample_path": str(sample.sample_path),
        "sample_group": sample.sample_group,
        "sample_number": sample.sample_number,
        "sample_category": sample_spec.get("category") or "uncategorized",
        "sample_label": sample_spec.get("label") or sample.sample_path.name,
        "provider": provider,
        "parser_provider": provider,
        "strategy": plan.get("strategy"),
        "document_subtype": plan.get("document_subtype"),
        "status": extraction_status,
        "quality": quality.get("quality"),
        "can_chunk": quality.get("can_chunk"),
        "requires_review": quality.get("requires_review"),
        "review_reason": _parser_review_reason(quality, warnings),
        "text_length": len(extraction_text),
        "text_snippet": _snippet(extraction_text),
        "page_count": extraction_page_count,
        "seconds": attempt.get("seconds"),
        "local_only": bool(provider_status.get("local_only", True)),
        "provider_available": bool(provider_status.get("available", True)),
        "warnings": warnings,
        "dependency_status": provider_status,
        "provider_attempt": attempt,
        "metadata": {
            "benchmark": True,
            "sample_metadata": sample_spec.get("metadata") or {},
            "extraction_metadata": extraction_metadata,
        },
    }


def _parser_review_reason(quality: dict[str, Any], warnings: list[str]) -> str | None:
    if quality.get("requires_review"):
        return str(quality.get("reason") or quality.get("quality") or "parser_quality_requires_review")
    if warnings:
        return "parser_warnings_present"
    return None


def _snippet(text: str, limit: int = 500) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _benchmark_samples(
    input_paths: list[str | Path],
    *,
    sample_manifest: str | Path | None,
    sample_root: str | Path | None,
) -> list[dict[str, Any]]:
    if sample_manifest:
        return load_provider_benchmark_samples(sample_manifest, sample_root=sample_root)
    if not input_paths:
        raise ValueError("Provider benchmark requires explicit paths or sample_manifest")
    return [{"path": Path(path), "category": _category_from_path(Path(path)), "label": Path(path).name, "metadata": {}} for path in input_paths]


def _filter_samples(
    samples: list[dict[str, Any]],
    *,
    sample_categories: list[str] | None,
    sample_limit: int | None,
) -> list[dict[str, Any]]:
    filtered = samples
    categories = {category.strip() for category in sample_categories or [] if category.strip()}
    if categories:
        filtered = [sample for sample in filtered if str(sample.get("category") or "uncategorized") in categories]
    if sample_limit is not None:
        filtered = filtered[: max(0, int(sample_limit))]
    return filtered


def _providers(provider_names: list[str] | None) -> list[ExtractionProvider]:
    names = provider_names or ["current", "docling"]
    providers: list[ExtractionProvider] = []
    for name in names:
        normalized = name.strip().lower()
        if normalized == "current":
            providers.append(CurrentExtractionProvider())
        elif normalized == "docling":
            providers.append(DoclingExtractionProvider())
        elif normalized == "mineru":
            providers.append(MinerUExtractionProvider())
        elif normalized in {"ragflow_deepdoc", "deepdoc"}:
            providers.append(RAGFlowDeepDocExtractionProvider())
        elif normalized == "unstructured":
            providers.append(UnstructuredExtractionProvider())
        else:
            raise ValueError(f"Unsupported extraction benchmark provider: {name}")
    return providers


def _default_plan(sample: SampleFile) -> dict[str, Any]:
    suffix = sample.sample_path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json", ".jsonl", ".html", ".htm"}:
        return {"strategy": "text_extraction", "document_subtype": "born_digital_text"}
    if suffix in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}:
        return {"strategy": "ocr_page_level", "document_subtype": "image_scan"}
    if suffix == ".pdf":
        return {"strategy": "text_extraction", "document_subtype": "pdf"}
    return {"strategy": "deferred_technical", "document_subtype": "unknown", "defer_reason": "unsupported_benchmark_type"}


def _category_from_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json", ".jsonl", ".html", ".htm"}:
        return "born_digital_text"
    if suffix in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}:
        return "image_scan"
    if suffix == ".pdf":
        return "pdf"
    return "technical_deferred"


def _sample(path: Path, index: int, *, sample_spec: dict[str, Any]) -> SampleFile:
    return SampleFile(
        sample_path=path,
        source_path=str(path),
        relative_path=path.name,
        sample_group="provider-benchmark",
        sample_number=index,
        index_row={"metadata": {"benchmark_category": sample_spec.get("category"), **(sample_spec.get("metadata") or {})}},
    )


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_provider = _rows_by_provider(rows)
    return {
        "result_count": len(rows),
        "by_provider": _count(rows, "provider"),
        "provider_availability": {
            provider: {
                "available": all(bool(row.get("provider_available")) for row in provider_rows),
                "local_only": all(bool(row.get("local_only")) for row in provider_rows),
                "result_count": len(provider_rows),
            }
            for provider, provider_rows in by_provider.items()
        },
        "by_status": _count(rows, "status"),
        "by_quality": _count(rows, "quality"),
        "review_required_count": sum(1 for row in rows if row.get("requires_review")),
        "comparison": _comparison(rows),
        "local_only": all(bool(row.get("local_only")) for row in rows),
    }


def _count(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _rows_by_provider(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("provider") or "unknown"), []).append(row)
    return dict(sorted(grouped.items()))


def _comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_source: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        by_source.setdefault(str(row.get("source_path") or row.get("sample_path")), {})[str(row.get("provider"))] = row
    changed_quality = 0
    changed_status = 0
    text_length_deltas: list[int] = []
    for provider_rows in by_source.values():
        current = provider_rows.get("current")
        docling = provider_rows.get("docling")
        if not current or not docling:
            continue
        if current.get("quality") != docling.get("quality"):
            changed_quality += 1
        if current.get("status") != docling.get("status"):
            changed_status += 1
        text_length_deltas.append(int(docling.get("text_length") or 0) - int(current.get("text_length") or 0))
    return {
        "paired_file_count": len(text_length_deltas),
        "changed_quality_count": changed_quality,
        "changed_status_count": changed_status,
        "docling_minus_current_text_length_total": sum(text_length_deltas),
    }


def _provider_recommendations(rows: list[dict[str, Any]], *, max_average_seconds: float | None = 30.0) -> list[dict[str, Any]]:
    recommendations = []
    for provider, provider_rows in _rows_by_provider(rows).items():
        result_count = len(provider_rows)
        extracted_count = sum(1 for row in provider_rows if row.get("status") == "extracted")
        ok_count = sum(1 for row in provider_rows if row.get("quality") == "ok")
        review_required_count = sum(1 for row in provider_rows if row.get("requires_review"))
        available_count = sum(1 for row in provider_rows if row.get("provider_available"))
        local_only = all(bool(row.get("local_only")) for row in provider_rows)
        average_text_length = round(sum(int(row.get("text_length") or 0) for row in provider_rows) / result_count, 2) if result_count else 0
        average_seconds = round(sum(float(row.get("seconds") or 0) for row in provider_rows) / result_count, 4) if result_count else 0.0
        max_seconds = round(max((float(row.get("seconds") or 0) for row in provider_rows), default=0.0), 4)
        promotion_status = _promotion_status(
            result_count=result_count,
            extracted_count=extracted_count,
            ok_count=ok_count,
            review_required_count=review_required_count,
            available_count=available_count,
            local_only=local_only,
            average_seconds=average_seconds,
            max_average_seconds=max_average_seconds,
        )
        recommendations.append(
            {
                "provider": provider,
                "result_count": result_count,
                "available_rate": _rate(available_count, result_count),
                "extracted_rate": _rate(extracted_count, result_count),
                "ok_quality_rate": _rate(ok_count, result_count),
                "review_required_rate": _rate(review_required_count, result_count),
                "average_text_length": average_text_length,
                "average_seconds": average_seconds,
                "max_seconds": max_seconds,
                "max_average_seconds": max_average_seconds,
                "local_only": local_only,
                "promotion_status": promotion_status,
                "promotion_reason": _promotion_reason(promotion_status),
            }
        )
    return sorted(recommendations, key=lambda row: (row["promotion_status"] != "candidate", -row["ok_quality_rate"], -row["extracted_rate"], row["provider"]))


def _promotion_status(
    *,
    result_count: int,
    extracted_count: int,
    ok_count: int,
    review_required_count: int,
    available_count: int,
    local_only: bool,
    average_seconds: float,
    max_average_seconds: float | None,
) -> str:
    if result_count == 0:
        return "insufficient_data"
    if not local_only:
        return "blocked_not_local_only"
    if available_count < result_count:
        return "blocked_dependency_unavailable"
    if max_average_seconds is not None and average_seconds > max_average_seconds:
        return "needs_runtime_review"
    if extracted_count == result_count and ok_count == result_count and review_required_count == 0:
        return "candidate"
    return "needs_review"


def _promotion_reason(status: str) -> str:
    return {
        "candidate": "all benchmarked files extracted with ok quality and no review requirement",
        "blocked_dependency_unavailable": "provider dependency is unavailable for at least one benchmarked file",
        "blocked_not_local_only": "provider is not local-only",
        "needs_review": "benchmark output needs review before provider promotion",
        "needs_runtime_review": "provider quality is acceptable but average runtime exceeds the benchmark promotion threshold",
        "insufficient_data": "no benchmark rows were available",
    }[status]


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 4)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    import json

    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    import json

    with path.open("a", encoding="utf-8") as output_file:
        output_file.write(json.dumps(row, sort_keys=True) + "\n")


def _reset_incremental_artifacts(output_path: Path) -> None:
    for name in ("provider-benchmark-results.jsonl", "sample-parser-results.jsonl"):
        (output_path / name).write_text("", encoding="utf-8")


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, indent=2, sort_keys=True) + "\n"
