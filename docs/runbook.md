# Sunshine Club Runbook

Last updated: 2026-05-28.

## Services

Default stack (Docker Compose):

| Service | Purpose | Port |
|---|---|---|
| `api` | FastAPI admin and product API | 8000 |
| `dashboard` | Next.js review/runs/files UI | 3000 |
| `db` | Postgres + pgvector | 5432 |
| `temporal` | Durable LangGraph batch/single-file execution | 7233 |
| `temporal-ui` | Temporal workflow inspection | 8080 |
| `worker` | Temporal worker (`sunshine-pipeline` task queue) | opt-in profile |
| `qdrant` | Local vector search for chunks and labeled examples (V2) | 6333 |

## Starting The System

```bash
# Default: API + dashboard + Postgres + Temporal
docker compose up --build

# With Temporal worker
docker compose --profile worker up --build
```

Without the worker profile, use `Subprocess` as the execution backend in the Runs page.

## Health Checks

```bash
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8000/admin/system/local-infrastructure | jq
```

The local-infrastructure endpoint should show:
- `local_only: true`
- Postgres configured with complete V2 migrations
- Qdrant available when `SUNSHINE_VECTOR_STORE=qdrant`
- Temporal SDK and worker available, plus `temporal.address_reachable: true` when service is running
- Hosted third-party APIs disabled by policy

## Environment

Copy `.env.example` to `.env` and override local/private values:

```bash
cp .env.example .env
```

Key env vars:

```text
SUNSHINE_NAS_ROOT=/mnt/sunshine
DATABASE_URL=postgresql://sunshine:local@localhost:5432/sunshine_club
SUNSHINE_VECTOR_STORE=qdrant
SUNSHINE_QDRANT_URL=http://localhost:6333
TEMPORAL_ADDRESS=localhost:7233
SUNSHINE_RUN_EXECUTION_BACKEND=subprocess   # or: temporal
SUNSHINE_REVIEW_DB_PATH=.local/sunshine-review.sqlite  # SQLite store (V1)
CORTEX_BASE_URL=https://cortex.vallery.net
CORTEX_API_KEY=<cortex bearer key>
OPENAI_BASE_URL=https://cortex.vallery.net/v1  # route OpenAI-compatible calls to Cortex
OPENAI_API_KEY=<cortex bearer key>
```

**Never commit raw API keys.** The pipeline normalizes env aliases at runtime.

Set `SUNSHINE_RUN_EXECUTION_BACKEND=temporal` only when Temporal and the worker are running.

## Running Without Docker (Development)

Start API:
```bash
.venv/bin/uvicorn sunshine_api.main:app --host 0.0.0.0 --port 8000
```

Start dashboard:
```bash
SUNSHINE_API_URL=http://localhost:8000 npm --workspace apps/dashboard run dev
```

## Agent Worktrees

Each agent should have its own git worktree to avoid branch collisions.

| Worktree | Path | Branch | Purpose |
|---|---|---|---|
| Canonical integration | `/home/james/projects/active/sunshine_club` | `main` | Integration merges and verification |
| Backend / project lead | `/home/james/projects/active/sunshine_club_backend` | `backend/main-agent` | Backend, extraction, OCR, LangGraph, DB, API, tests |
| Frontend review | `/home/james/projects/active/sunshine_club_frontend` | `frontend-review/agent` | Dashboard UX, tables, filters, visual polish |

**Do not switch branches in another agent's worktree.**

Backend agent owns: backend, extraction, OCR, embeddings, LangGraph, DB schema, API routes, tests, run orchestration, integration decisions.

Frontend review agent owns: dashboard UX, layout, accessibility, visual polish, table/filter behavior, frontend review tooling. Should avoid backend/API/schema changes unless explicitly requested.

### Ports

Backend agent: API port `8001`, dashboard port `3001`
Frontend review agent: API port `8002`, dashboard port `3002`

```bash
# Backend agent
cd /home/james/projects/active/sunshine_club_backend
export SUNSHINE_REVIEW_DB_PATH=.local/backend-review.sqlite
.venv/bin/uvicorn sunshine_api.main:app --host 0.0.0.0 --port 8001
npm --workspace apps/dashboard run dev -- --hostname 0.0.0.0 --port 3001

# Frontend review agent
cd /home/james/projects/active/sunshine_club_frontend
export SUNSHINE_REVIEW_DB_PATH=.local/frontend-review.sqlite
.venv/bin/uvicorn sunshine_api.main:app --host 0.0.0.0 --port 8002
npm --workspace apps/dashboard run dev -- --hostname 0.0.0.0 --port 3002
```

**Do not share `node_modules` or `.venv` between worktrees via symlinks.** Turbopack rejects `node_modules` symlinks outside the project root. A shared editable Python venv can import from the wrong worktree.

### Mac Tunnels

```bash
# Backend agent
ssh -N -L 3001:127.0.0.1:3001 -L 8001:127.0.0.1:8001 james@192.168.30.63
# Open: http://localhost:3001/runs

# Frontend review agent
ssh -N -L 3002:127.0.0.1:3002 -L 8002:127.0.0.1:8002 james@192.168.30.63
# Open: http://localhost:3002/review
```

### Merge Back To Main

```bash
cd /home/james/projects/active/sunshine_club
git switch main
git merge backend/main-agent
git merge frontend-review/agent
.venv/bin/python -m pytest -q
npm --workspace apps/dashboard run build
```

### Worktree Cleanup

```bash
git worktree list
git worktree remove /home/james/projects/active/sunshine_club_frontend
```

## Cortex (Private LLM Gateway)

Gateway: `https://cortex.vallery.net`

Cortex is a private OpenAI-compatible inference and RAG gateway. Connect to the public gateway only — do not call internal vLLM, TEI, Qdrant, SQLite, OCR, or Docker services directly.

### Quick Start

```python
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://cortex.vallery.net/v1",
    api_key=os.environ["CORTEX_API_KEY"],
)
response = client.chat.completions.create(
    model="gemma4-26b",
    messages=[{"role": "user", "content": "Say OK."}],
    temperature=0.2,
    max_tokens=100,
)
print(response.choices[0].message.content)
```

### Current Models

| Capability | Model/service |
|---|---|
| Chat | `gemma4-26b` (vLLM, max context 131,072 tokens) |
| Responses | `gemma4-26b` (maps `/v1/responses` to vLLM chat) |
| Embeddings | `Qwen/Qwen3-Embedding-0.6B` (TEI, 1024-dimensional) |
| OCR | `paddleocr-ppocr-cpu` (CPU OCR for PDF/image) |
| Rerank | `cortex-lexical-rerank` (lightweight lexical scorer) |
| Retrieval | Qdrant + SQLite FTS (dense, keyword, hybrid search) |
| Managed RAG | Gateway orchestrator (retrieval, reranking, generation, citations) |

**Embedding batch size:** Keep inputs under ~900–1000 tokens per item. The live CPU TEI service serializes requests. Use gateway ingestion endpoints for bulk document indexing instead of embedding directly.

### Authentication

Keys look like: `crag_live_project_<project_id>_key_<key_id>_<secret>`

All endpoints require `Authorization: Bearer <key>` except `GET /health`.

OIDC path (Authentik at `https://auth.vallery.net`): use only when testing OIDC compatibility. For service agents, use long-lived Cortex API keys.

### Scopes

| Endpoint family | Scope |
|---|---|
| `/v1/chat/completions` | `chat` |
| `/v1/responses`, `/v1/rag/query` | `responses` |
| `/v1/embeddings` | `embeddings` |
| `/v1/ocr` | `ocr` |
| `/v1/rerank` | `rerank` |
| `/v1/retrieve`, `/v1/search` | `retrieve` |
| `/v1/collections`, `/v1/documents` | `documents` |
| `/v1/ingest-jobs` | `ingest` |

A key with `*` uses all endpoints.

### Key Endpoints

**Health (unauthenticated):** `GET /health` — liveness check for load balancers.

**Readiness:** `GET /ready` — verifies LLM, embeddings, OCR, Qdrant, and auth mode.

**Chat:** `POST /v1/chat/completions` — OpenAI-compatible. Prefer `gemma4-26b`. Use non-streaming for tool-call workflows unless vLLM streaming behavior is verified.

**Embeddings:** `POST /v1/embeddings` with `model: "Qwen/Qwen3-Embedding-0.6B"`, `encoding_format: "float"`. Returns 1024-dimensional vectors.

**OCR:** `POST /v1/ocr` — upload PDF/image as multipart. Returns page-level text.

**Managed RAG query:** `POST /v1/rag/query` — retrieval, optional reranking, context packing, generation, citations in one call.

**Collections:** `POST /v1/collections` to create, `GET /v1/collections/{id}`, `PATCH /v1/collections/{id}`.

**Documents:** `POST /v1/documents` with JSON text or multipart file upload. For PDFs/images, gateway runs OCR pre-pass. Response includes `ingest_job.id`.

**Ingest job status:** `GET /v1/ingest-jobs/{job_id}`. Statuses: `queued`, `running`, `completed`, `failed`. Retry: `POST /v1/ingest-jobs/{job_id}/retry`.

**Limitations:** Streaming is disabled on `/v1/responses`. OpenAI hosted tools (`web_search`, `file_search`, `computer_use`, `code_interpreter`, `mcp`) are not available.

## Monorepo Structure

```text
sunshine_club/
  apps/
    api/                    # FastAPI admin and product API
    dashboard/              # Next.js admin dashboard
    worker/                 # Temporal worker entrypoints
  packages/
    core/                   # domain contracts and pure decision logic
    connectors/             # NAS and later Google Drive connectors
    extraction/             # Docling/OCR/Marker adapters + LangGraph pipeline
    workflows/              # LangGraph graph definitions (foundation_graph.py)
  infra/
    db/migrations/          # Postgres and pgvector migrations
    terraform/              # GCP infrastructure (later)
  docs/
  tests/
```

## Scrapbook / Newspaper Safety

Long scrapbook, newspaper, and mixed historical PDFs are treated as **immutable parent files**. The V2 graph may create logical page-range segment proposals, but automated runs must not physically split, delete, or rewrite source PDFs. Segment decisions happen through the dashboard and become training evidence before any future export/promote action creates child documents.

## Roadmap

### Phase 1: Foundation

Build: monorepo skeleton, database and migrations, dashboard shell, API shell, worker shell, connector interfaces, Verdify taxonomy seed loading contract.

Exit: apps boot locally, migrations run, baseline contracts exist, NAS `/mnt/sunshine` defined as Phase 1 source root, taxonomy handoff can be represented as folders/tags/facets/placement rules/privacy/reviewer roles.

### Phase 2: Extraction and Classification Core

Build: NAS connector, extraction pipeline, content-class-specific extraction (documents, scans/images, spreadsheets, email, photos, manifests), chunking and embeddings, classifier outputs, candidate tag scoring.

Exit: sample files from mounted corpus can be processed end to end; classifier outputs top candidates and margin.

### Phase 3: Tag and Placement Control Layer

Build: tags, tag facets/groups, folders, tag-folder mappings, placement rules, deterministic path resolution, privacy/access policy, reviewer-role defaults.

Exit: primary tag + metadata resolves to a deterministic destination path; restricted privacy classes excluded from normal search/chat.

### Phase 4: Review System

Build: low-confidence queue, duplicate queue, ignore flow, new-tag creation flow, misfiled-file queue, missing destination queue, privacy review queue, date confirmation, person-identification, source-verification, publication-approval, family-return queues.

Exit: every non-auto-routable item can be resolved through the dashboard.

### Phase 5: Drive Action Engine

Build: action queue, move actions, staged import actions, rollback support, mapping migration batches.

Exit: semantic assignment and physical movement tracked separately; failed moves recoverable.

### Phase 6–7: Historical Import and NAS Migration

Build: organized import plan for NAS → Drive, possible-misfiled detection, review-driven move proposals, import validation, canonicalization rules.

Exit: staged corpus can be imported into Drive with controlled placement decisions; original copies retained.

### Phase 8: Intake and Ongoing Auto-Routing

Build: dashboard upload flow, universal intake folder lifecycle, processing statuses, high-confidence auto-routing.

Exit: new files can flow from upload → intake → final destination.

### Phase 9: Search and Chat

Build: semantic search, tag filtering, related files, grounded chat, explanation surfaces.

Exit: users can find and understand files without browsing Drive directly.

### Phase 10: Learning and Tuning

Build: review decision capture, bounded learning loop, threshold tuning, observability and routing metrics.

Exit: review burden trends downward; routing quality improves over time without uncontrolled drift.

## Quality Milestones (Current Priority)

In priority order:

### 1. Golden Label Set (50–100 files)

Required files: Tea folder samples, a finance workbook, a yearbook/OCR item, a scrapbook page, a true photo, a scanned obituary, an email, a governance/policy doc, a dental program item, a manifest/workspace artifact.

Required fields: `source_path`, `relative_path`, `filename`, `content_class`, `correct_primary_tag`, `correct_secondary_tags`, `reviewer`, `notes`, `evidence_snippet`, `created_at`.

### 2. Semantic Index Build

Run: `POST /admin/semantic-index/build`

Verify: `GET /admin/semantic-index/status` shows all golden labels with non-empty snippets. Zero labels with empty/weak snippets.

### 3. LLM Tagging Evaluation

Run semantic eval for the 50–100 golden label set. Report: primary accuracy, confusion pairs, review rate, auto-accept precision, mismatch queue.

Success: `>=70%` primary accuracy on QA sample, LLM tag failures fall back to deterministic rather than crashing, deterministic `Tea`-style incidental keywords no longer dominate when OCR text is richer.

### 4. OCR Quality Baseline

For the scanned-document QA sample, report: `ok` vs `poor` vs `empty` OCR quality distribution, OCR fallback trigger rate, text length distribution, gibberish detection accuracy.

Success: `>=80%` of scanned documents produce `ok` or `poor`-but-useful OCR text; `<5%` produce empty/unusable text without routing to review.

### 5. Run-to-Run Comparison

After any pipeline change: verify review-required rate does not increase for the wrong reason (more items going to review is acceptable if classification is more cautious; more items going to review because of broken confidence logic is not).
