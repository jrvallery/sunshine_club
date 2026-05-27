# Sunshine Club

Sunshine Club is a Google Drive intelligence and organization system.

Its job is to:

- classify messy documents into a controlled tag system
- route files into canonical Google Drive folders
- stage low-confidence and duplicate cases for review
- keep new uploads organized over time
- power search, related discovery, and grounded chat on top

Google Drive is the production source of truth for organized files.

Phase 1 works from the Atlas VM NAS mount at `/mnt/sunshine`. See
`docs/corpus-inventory.md` for the current source groups, file types, and
pipeline implications.

The current taxonomy source of truth is the Verdify handoff and seed files in
`docs/`, summarized in `docs/taxonomy.md`.

The documentation lives in `docs/`.

## Development

Use the local Python virtual environment for fast unit tests and Python service
work:

```bash
python3 -m virtualenv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest -q
```

Install dashboard dependencies from the repository root:

```bash
npm install
npm --workspace apps/dashboard run build
```

## Docker

The default Compose stack runs the current local development topology:

- FastAPI API on `http://localhost:8000`
- Next.js dashboard on `http://localhost:3000`
- Postgres with pgvector on `localhost:5432`
- Temporal on `localhost:7233`
- Temporal UI on `http://localhost:8080`

Start it with:

```bash
docker compose up -d --build
```

Check the API:

```bash
curl http://localhost:8000/healthz
```

Run Python tests inside the API image:

```bash
docker compose run --rm api pytest -q
```

Stop the stack:

```bash
docker compose down
```

Reset local container data, including the initialized Postgres volume:

```bash
docker compose down -v
```

The worker service is containerized but not part of the default stack because
the Temporal worker entrypoint is still a placeholder. Run it explicitly after
the worker is implemented:

```bash
docker compose --profile worker up worker
```

Compose mounts the NAS corpus read-only at `/mnt/sunshine` by default. Override
the host path with `SUNSHINE_NAS_ROOT=/path/to/corpus` if needed.

## NAS Inventory

Generate a reviewable corpus inventory from the mounted NAS root:

```bash
source .venv/bin/activate
python -m sunshine_connectors.inventory /mnt/sunshine \
  --output /mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/inventory.jsonl \
  --summary /mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/summary.json \
  --skipped-audit /mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/skipped-files.jsonl \
  --probe-manifest /mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/probe-manifest.jsonl \
  --inventory-run-id sunshine-club-inventory-2026-05-25
```

The inventory skips known system junk and temp/cache paths, emits one JSON row
per included file, and writes a summary with counts by source collection,
content class, extension, skipped reason, low-confidence assignments,
`binary_or_unknown` files, and files needing extraction probes.

The skipped-file audit and probe manifest are the safety artifacts for the next
extraction pass. They keep skipped paths reviewable and isolate low-confidence,
unknown, PDF, and image cases that require extraction evidence before trust.

Run the lightweight content-class probe pass:

```bash
source .venv/bin/activate
python -m sunshine_extraction.probe \
  /mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/probe-manifest.jsonl \
  --results /mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/probe-results.jsonl \
  --summary /mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/probe-summary.json \
  --probe-run-id sunshine-club-probe-2026-05-25
```

The probe pass reads files but does not mutate source data or overwrite the
inventory. It emits one result row per probe manifest row plus a summary of
unchanged, changed, failed, still-unknown, and review-required files.

## Embedding Smoke Test

Validate Cortex embedding configuration without exposing the API key:

```bash
source .venv/bin/activate
export SUNSHINE_EMBEDDING_PROVIDER=cortex
export CORTEX_BASE_URL=https://cortex.vallery.net
export CORTEX_API_KEY=...
export SUNSHINE_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
export SUNSHINE_EMBEDDING_DIMENSIONS=1024

python -m sunshine_extraction.embeddings \
  --text "Sunshine Club embedding smoke test."
```

Expected output includes `"embedding_status": {"embedded": 1}` and
`"dimensions": 1024`. If `SUNSHINE_EMBEDDING_PROVIDER` is unset, the command
uses deterministic placeholder vectors and reports `"placeholder"` instead.

## QA Sample Pipeline

Run the tracer-bullet pipeline over the deterministic QA sample set:

```bash
source .venv/bin/activate
python -m sunshine_extraction.sample_pipeline \
  --input-root "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples" \
  --output-dir "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/sample-pipeline"
```

The runner writes `sample-inputs.jsonl`, extraction results, chunks,
embeddings, LLM tag inspections, tag candidates, final route/review rows, and
`sample-pipeline-summary.json`. It reads copied QA files only and does not move,
modify, or delete source files.

Enable structured LLM tag inspection from the shell where `GEMINI_API_KEY` is
set:

```bash
export SUNSHINE_LLM_TAG_MODEL=gemini-2.5-flash
python -m sunshine_extraction.sample_pipeline \
  --enable-llm-tags \
  --input-root "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples" \
  --output-dir "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/sample-pipeline-llm"
```
