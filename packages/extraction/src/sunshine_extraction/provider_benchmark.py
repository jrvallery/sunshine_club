"""CLI compatibility entry point for local provider benchmarks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sunshine_extraction.evals.provider_benchmark import benchmark_extraction_providers


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark local extraction providers on selected files.")
    parser.add_argument("paths", nargs="+", help="Files to benchmark.")
    parser.add_argument("--providers", default="current,docling", help="Comma-separated providers: current,docling.")
    parser.add_argument("--output-dir", help="Optional output directory for benchmark artifacts.")
    args = parser.parse_args()
    provider_names = [name.strip() for name in args.providers.split(",") if name.strip()]
    result = benchmark_extraction_providers([Path(path) for path in args.paths], provider_names=provider_names, output_dir=args.output_dir)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
