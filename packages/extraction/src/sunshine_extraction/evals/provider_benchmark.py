"""Local extraction provider benchmark runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sunshine_extraction.providers.extraction import CurrentExtractionProvider, DoclingExtractionProvider, ExtractionProvider
from sunshine_extraction.services.content import SampleFile
from sunshine_extraction.services.extraction import OcrArtifacts, ocr_executor_from_env, extraction_quality_gate


def benchmark_extraction_providers(
    input_paths: list[str | Path],
    *,
    provider_names: list[str] | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    providers = _providers(provider_names)
    output_path = Path(output_dir) if output_dir is not None else None
    if output_path is not None:
        output_path.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for index, input_path in enumerate(input_paths, start=1):
        sample = _sample(Path(input_path), index)
        plan = _default_plan(sample)
        for provider in providers:
            rows.append(_benchmark_one(sample, plan, provider))
    summary = _summary(rows)
    if output_path is not None:
        _write_jsonl(output_path / "provider-benchmark-results.jsonl", rows)
        (output_path / "provider-benchmark-summary.json").write_text(_json_dumps(summary), encoding="utf-8")
    return {"summary": summary, "results": rows}


def _benchmark_one(sample: SampleFile, plan: dict[str, Any], provider: ExtractionProvider) -> dict[str, Any]:
    status = provider.dependency_status()
    ocr_artifacts = OcrArtifacts(pages=[], documents=[])
    extraction, attempt = provider.extract(sample, plan, ocr_executor=ocr_executor_from_env(), ocr_artifacts=ocr_artifacts)
    quality = extraction_quality_gate(extraction)
    return {
        "source_path": sample.source_path,
        "relative_path": sample.relative_path,
        "sample_path": str(sample.sample_path),
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


def _providers(provider_names: list[str] | None) -> list[ExtractionProvider]:
    names = provider_names or ["current", "docling"]
    providers: list[ExtractionProvider] = []
    for name in names:
        normalized = name.strip().lower()
        if normalized == "current":
            providers.append(CurrentExtractionProvider())
        elif normalized == "docling":
            providers.append(DoclingExtractionProvider())
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


def _sample(path: Path, index: int) -> SampleFile:
    return SampleFile(
        sample_path=path,
        source_path=str(path),
        relative_path=path.name,
        sample_group="provider-benchmark",
        sample_number=index,
        index_row={"metadata": {}},
    )


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "result_count": len(rows),
        "by_provider": _count(rows, "provider"),
        "by_status": _count(rows, "status"),
        "by_quality": _count(rows, "quality"),
        "review_required_count": sum(1 for row in rows if row.get("requires_review")),
        "local_only": all(bool(row.get("local_only")) for row in rows),
    }


def _count(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    import json

    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, indent=2, sort_keys=True) + "\n"
