"""CLI entry point for local provider benchmarks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sunshine_extraction.evals.provider_benchmark import benchmark_extraction_providers


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
    args = parser.parse_args()
    provider_names = [name.strip() for name in args.providers.split(",") if name.strip()]
    result = benchmark_extraction_providers(
        [Path(path) for path in args.paths],
        provider_names=provider_names,
        output_dir=args.output_dir,
        sample_manifest=args.sample_manifest,
        sample_root=args.sample_root,
    )
    print(json.dumps(result["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
