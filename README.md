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
  --summary /mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/summary.json
```

The inventory skips known system junk and temp/cache paths, emits one JSON row
per included file, and writes a summary with counts by source collection,
content class, extension, skipped reason, low-confidence assignments,
`binary_or_unknown` files, and files needing extraction probes.
