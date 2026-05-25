# Sunshine Club Implementation Plan

This plan translates the current docs into an implementation sequence for V1.

## Architecture Being Implemented

Sunshine Club is a document intelligence and organization system. V1 is built around the local/NAS corpus mounted on Atlas at `/mnt/sunshine`, not live Google Drive crawling.

The core loop is:

1. register a staged file from the NAS corpus
2. capture source collection, path, size, mtime, extension, MIME type, checksum, and content class
3. extract text and metadata through the content-class-specific path
4. store the normalized extraction artifact with quality, warnings, and structured page/block/table output
5. revise content class when extraction evidence proves the initial inventory class was wrong
6. classify candidate primary routing tag and secondary facets from extracted evidence and quality signals
7. persist classification evidence and confidence
8. resolve a deterministic destination path from primary tag, folder mapping, and placement rule
9. create either a review task or a pending Drive import/move action

Search, related discovery, and grounded chat are downstream consumers of this organized semantic state.

## Contradictions and Resolutions

- `docs/technical-plan.md` is now an index into the newer doc set, not the source architecture. Resolution: treat the newer docs as authoritative.
- Earlier queue-oriented assumptions should not be reintroduced. The current stack baseline uses Temporal for durable execution. Resolution: use Temporal for long-running ingestion, review waits, import batches, and action execution.

## Phase-Mapped Implementation Plan

### Phase 1: Foundation

Deliver:

- monorepo skeleton
- FastAPI app shell
- dashboard shell
- worker shell
- core domain contracts
- initial Postgres migration
- NAS source root configuration for `/mnt/sunshine`
- corpus inventory contracts for source collection and content class
- Verdify taxonomy seed representation for folders, primary tags, facets, placement rules, privacy, and reviewer roles

Exit criteria:

- services have clear boundaries
- migrations define operational state
- the first thin slice can run against explicit contracts

### Phase 2: Extraction and Classification Core

Deliver:

- NAS filesystem connector
- Docling extraction adapter
- OCRmyPDF/Tesseract fallback adapter for scanned PDFs
- TIFF and image OCR path for historical scans
- normalized extraction artifact contract for page/block/table output
- extraction quality and warnings policy
- content-class revision policy after extraction
- photo metadata path for low-text event/member photos
- spreadsheet extraction that preserves sheet names and row/table structure
- email extraction that preserves headers, dates, body, and attachments
- chunking contracts
- embedding write path
- classification run persistence
- confidence and margin policy

Exit criteria:

- sample files from the mounted corpus can produce content-class-specific extraction artifacts, classification candidates, margin, and explanation

### Phase 3: Tag and Placement Control Layer

Deliver:

- tag CRUD for admin
- tag facets / tag groups from the Verdify handoff
- folder registry
- tag-folder mappings
- placement rules
- document privacy/access policy
- reviewer-role routing defaults
- deterministic path resolver

Exit criteria:

- a primary tag plus metadata resolves to a deterministic Drive destination or a blocked review state
- secondary facet assignments remain distinguishable by facet group
- restricted privacy classes are excluded from normal search/chat by policy

### Phase 4: Review System

Deliver:

- low-confidence review queue
- duplicate review queue
- missing destination review queue
- privacy review queue
- date confirmation queue
- person identification queue
- source verification queue
- publication approval queue
- family-return review queue
- ignore workflow
- human decision capture

Exit criteria:

- every non-auto-routable item can be resolved through admin workflows

### Phase 5: Drive Action Engine

Deliver:

- action queue table
- import-to-Drive action contract
- move action contract
- idempotency keys
- retry/error lifecycle
- rollback action records

Exit criteria:

- semantic assignment and physical movement are tracked separately

### Phase 6-10: Import, Intake, Search, Chat, Learning

Build after the admin control loop is stable:

- NAS import planning into Drive
- production upload intake
- semantic search and tag filters
- related discovery
- grounded chat
- learning signals from review outcomes
- threshold tuning and observability dashboards

## Proposed Monorepo Structure

```text
sunshine_club/
  apps/
    api/                    # FastAPI admin and product API
    dashboard/              # Next.js admin dashboard shell
    worker/                 # Temporal worker entrypoints
  packages/
    core/                   # domain contracts and pure decision logic
    connectors/             # NAS and later Google Drive connectors
    extraction/             # Docling/OCR/Marker adapters
    workflows/              # LangGraph graph definitions
  infra/
    db/migrations/          # Postgres and pgvector migrations
    terraform/              # GCP infrastructure later
  docs/
  tests/
```

## Proposed Database Schema Outline

Initial tables:

- `documents`: one row per known file, including source type, source collection, source path/id, file type metadata, content class, checksum, processing status, canonical flag, and raw metadata.
- `extraction_artifacts`: normalized OCR/parser output, structured payload, quality, warnings, and content-class before/after evidence.
- `document_chunks`: normalized text chunks for retrieval and evidence.
- `chunk_embeddings`: pgvector embeddings keyed by chunk and model.
- `tags`: controlled taxonomy with stable tag keys, display names, primary/secondary tag kinds, and facet/tag group for secondary terms.
- `folders`: manually registered Drive folder targets.
- `tag_folder_mappings`: one active folder mapping per primary tag.
- `placement_rules`: deterministic subfolder rules per primary tag.
- `document_tag_assignments`: proposed, applied, or rejected primary/secondary tag assignments.
- `document_policy`: enforceable privacy/access, processing status, usage, and reviewer-role policy.
- `document_dates`: date value, date granularity, date confidence, date source, and evidence.
- `classification_runs`: classifier candidates, score, margin, explanation, evidence, and extraction quality.
- `document_relationships`: duplicate, near-duplicate, related, and possible-newer-version links.
- `review_tasks`: low-confidence, duplicate, missing-destination, misfiled, privacy, date, person-identification, source-verification, publication, family-return, and migration review work.
- `human_decisions`: structured review outcomes for audit and later learning.
- `drive_actions`: pending/applied/failed/rolled-back import and move actions.
- `migration_batches`: controlled import and mapping-change batches.
- `audit_events`: append-only product and workflow events.
- `runtime_guard_events`: loop, retry, budget, and kill-switch guard records.

## Workflow Boundaries

### FastAPI

- receives admin and dashboard requests
- validates request/response contracts
- exposes review, taxonomy, action, and status APIs
- starts Temporal workflows
- reads current state from Postgres

### LangGraph

- models the controlled decision graph:
  - extraction complete
  - classification complete
  - duplicate check complete
  - confidence gate
  - placement resolution
  - review interrupt or action creation
- does not own durable operational truth
- does not become a multi-agent swarm

### Temporal

- runs durable ingestion, classification, review-wait, import, and action workflows
- handles retries, timeouts, workflow history, and resumption
- calls LangGraph decision flows inside bounded activities or workflow steps

### Postgres

- stores semantic state, review state, action state, audit state, and vector state
- remains the source of truth for tags and classification state
- does not delegate semantic truth to Google Drive metadata

## First Thin Slice

Implement a foundation flow that:

1. accepts a staged NAS file record
2. persists a document record
3. stores source collection and content class
4. runs stub extraction
5. runs deterministic stub classification against Verdify-seeded primary tags and secondary facets
6. checks confidence and margin thresholds
7. resolves destination path from primary tag, mapping, folder, and placement rule
8. emits either:
   - a review task for low confidence, duplicate hold, or missing destination
   - a pending `import_to_drive` action with the resolved destination path

This slice intentionally uses stub extraction/classification. It proves the contracts, state split, and deterministic routing path before integrating Docling, OCR, embeddings, LangGraph, and Temporal execution.
