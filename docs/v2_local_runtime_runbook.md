# Sunshine V2 Local Runtime Runbook

This runtime is local-only by default. Source corpus files stay mounted read-only, generated artifacts stay under configured output directories, and model/data infrastructure runs on the VM or private Cortex gateway.

## Services

| Service | Purpose | Default port |
| --- | --- | --- |
| Postgres + pgvector | durable V2 run, review, chunk, embedding, and audit tables | `5432` |
| Qdrant | local vector search for chunks and labeled examples | `6333` |
| Temporal | durable LangGraph batch/single-file execution | `7233` |
| Temporal UI | workflow inspection | `8080` |
| API | FastAPI dashboard/admin backend | `8000` |
| Dashboard | Next.js review/runs/files UI | `3000` |
| Worker | Temporal worker for `sunshine-pipeline` task queue | profile `worker` |

## Start

```bash
docker compose --profile worker up --build
```

Use the worker profile when testing Temporal-backed runs. Without the profile, dashboard runs should use the `subprocess` backend.

## Dashboard Run Backend

The Runs page exposes an `Execution backend` selector:

- `Subprocess`: development/default path. Runs the batch command directly from the API process.
- `Temporal`: production-shaped path. Starts `BatchPipelineWorkflow` on the local Temporal service and worker.

The selected backend is stored in run metadata and appears in run history and run reports.

## Health Checks

```bash
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8000/admin/system/local-infrastructure | jq
```

The local infrastructure endpoint should show:

- `local_only: true`
- Postgres configured with complete V2 migrations
- Qdrant available when `SUNSHINE_VECTOR_STORE=qdrant`
- Temporal SDK and worker module available
- hosted third-party APIs disabled by policy

## Environment

Copy `.env.example` to `.env` and override only local/private values:

```bash
cp .env.example .env
```

Important defaults:

- `SUNSHINE_NAS_ROOT=/mnt/sunshine`
- `DATABASE_URL=postgresql://sunshine:local@localhost:5432/sunshine_club`
- `SUNSHINE_VECTOR_STORE=qdrant`
- `SUNSHINE_QDRANT_URL=http://localhost:6333`
- `TEMPORAL_ADDRESS=localhost:7233`
- `SUNSHINE_RUN_EXECUTION_BACKEND=subprocess`

Set `SUNSHINE_RUN_EXECUTION_BACKEND=temporal` only when Temporal and the worker are running.

## Scrapbook/Newspaper Packets

Long scrapbook, newspaper, and mixed historical PDFs are handled as immutable parent files. The V2 graph may create logical page-range segment proposals, but automated runs must not physically split, delete, or rewrite source PDFs. Segment decisions happen through the dashboard and become training evidence before any future export/promote action creates child documents.
