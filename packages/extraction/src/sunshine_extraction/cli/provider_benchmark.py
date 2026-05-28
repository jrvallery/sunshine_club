"""CLI entry point for local provider benchmarks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sunshine_extraction.evals.provider_benchmark import benchmark_extraction_providers
from sunshine_extraction.evals.provider_benchmark_samples import generate_provider_benchmark_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark local extraction providers on selected files.")
    parser.add_argument("paths", nargs="*", help="Files to benchmark.")
    parser.add_argument(
        "--providers",
        default="current,docling",
        help="Comma-separated providers: current, docling, mineru, ragflow_deepdoc, unstructured.",
    )
    parser.add_argument("--output-dir", help="Optional output directory for benchmark artifacts.")
    parser.add_argument("--sample-manifest", help="JSON manifest containing canonical benchmark sample paths.")
    parser.add_argument("--sample-root", help="Optional root for resolving relative sample manifest paths.")
    parser.add_argument("--sample-categories", help="Optional comma-separated sample categories to run from the manifest.")
    parser.add_argument("--sample-limit", type=int, help="Optional maximum number of manifest samples to run after category filtering.")
    parser.add_argument("--max-average-seconds", type=float, default=30.0, help="Maximum average seconds per provider before promotion requires runtime review.")
    parser.add_argument("--generate-manifest-from-qa-root", help="QA samples root containing grouped index.jsonl files.")
    parser.add_argument("--manifest-output", default=".local/provider-benchmark-canonical-samples.json")
    parser.add_argument("--manifest-per-category", type=int, default=2)
    args = parser.parse_args()
    if args.generate_manifest_from_qa_root:
        result = generate_provider_benchmark_manifest(
            args.generate_manifest_from_qa_root,
            args.manifest_output,
            per_category=args.manifest_per_category,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    provider_names = [name.strip() for name in args.providers.split(",") if name.strip()]
    result = benchmark_extraction_providers(
        [Path(path) for path in args.paths],
        provider_names=provider_names,
        output_dir=args.output_dir,
        sample_manifest=args.sample_manifest,
        sample_root=args.sample_root,
        sample_categories=[category.strip() for category in (args.sample_categories or "").split(",") if category.strip()],
        sample_limit=args.sample_limit,
        max_average_seconds=args.max_average_seconds,
    )
    print(json.dumps(result["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
