# Sunshine Club Dashboard

Last updated: 2026-05-28.

## Summary

The review dashboard is the operating console for file inspection, review, training, and batch iteration. The goal is to eliminate terminal-based workflows for the core product loop:

```
run pipeline → review run-specific queue → correct labels → compare next run → measure improvement
```

## Current State

Already present:
- Next.js dashboard in `apps/dashboard`.
- FastAPI admin API in `apps/api`.
- SQLite review store.
- Review queue page with decision workflow.
- File browser with search, facets, inspector, preview, single-file run action.
- Runs page with preset launcher, per-run report, event log, artifact links.
- Golden labels page.
- Reports page.
- LangGraph pipeline runner.
- OCR fallback and text quality validation.
- Semantic tagging evaluation support.
- TanStack Query/Table/Virtual in dashboard pages.
- shadcn/ui component system.

Current gaps:
- Review items don't expose run id/run key in the table or allow filtering by run.
- File browsing not yet reliable enough to replace manual path inspection.
- Golden labels need cleaner create/edit/compare/reuse UX.
- Preview needs to show original file, OCR text, tags, evidence, placement, warnings, and raw JSON in one place.
- Better run-to-run comparison so incorrect classifications become visible quickly.

## Product Architecture

```text
Next.js Dashboard
  /review
  /files
  /runs
  /golden-labels
  /semantic-index
  /reports
      |
      v
FastAPI Admin API
  file search and preview
  review queue and decisions
  golden labels
  run presets and run events
  semantic index build/search
  semantic eval reports
      |
      v
SQLite Operational Store
  file_index
  pipeline_results
  review_items
  golden_labels
  pipeline_runs
  pipeline_run_events
      |
      v
LangGraph Pipeline
  single-file graph
  batch wrapper
  OCR extraction/fallback
  embeddings
  semantic tag judgment
  placement proposal
  audit artifacts
```

## Framework Choices

| Layer | Choice |
|---|---|
| App framework | Existing Next.js app router |
| UI components | `shadcn/ui` — shell, forms, tables, drawers, dialogs, tabs, badges, command palette, sidebar, tooltips, toasts |
| Tables | `@tanstack/react-table` — headless table state engine for review queue, file browser, run results, golden labels |
| API state | `@tanstack/react-query` — fetches, mutations, polling run events, optimistic updates, cache invalidation |
| Large lists | `@tanstack/react-virtual` — virtualized scrolling for large file/result tables |
| Forms | `react-hook-form` + `zod` — review decisions, run presets, filters, label correction |
| PDF preview | `react-pdf-viewer` or `pdf.js` — browser PDF viewing and page navigation |
| Image preview | Native image viewer first; add `OpenSeadragon` later for large scans |
| Charts | shadcn chart patterns or `recharts` — review volume, tag accuracy, OCR quality, run comparisons |

**Do not adopt Refine or react-admin yet.** This is a custom document review workbench, not a CRUD admin app. The hard screens are file preview, OCR comparison, semantic evidence, review decisions, run monitoring, and evaluation reports.

## Pages

### `/review`

Purpose: Resolve uncertain or audited pipeline results and create golden labels.

Table columns: filename, source collection, content class, primary tag, secondary tags, confidence, OCR quality, placement status, privacy state, route status, review reason, warning chips, latest reviewer.

Detail tabs: `Preview`, `Text` (OCR/extracted text with page/chunk metadata), `Tagging` (proposed tag, competing tags, nearest labels, LLM evidence), `Placement` (folder rule, proposed path, date evidence, privacy default), `History`, `Raw`.

Review actions: **Accept**, **Change** (class/primary tag/secondary tags/placement year/privacy state), **Defer** (OCR or technical), **Ignore**, **Duplicate**, **Next** (moves to next item without full page reload).

Every correction can be saved as a golden label. Every decision records reviewer, timestamp, previous value, corrected value, notes, and source evidence.

Default filters: status, route status, review reason, primary tag, content class, quality, placement status, warning type, source collection, **run id** (needed to see results from a specific run).

### `/files`

Purpose: Search and inspect corpus files independent of review queue.

Required filters: `q`, extension, content class, source collection, primary tag, secondary tag, OCR quality, latest run status, review state, placement state.

Search fields: filename, relative path, source path, extension, source collection, content class, latest primary tag, latest destination path, review status, OCR text snippet.

Preview behavior:

| Type | Behavior |
|---|---|
| PDF | Browser PDF viewer with extracted text beside it |
| JPG/PNG/TIF-derived | Fit/zoom/rotate image preview |
| TXT/MD/CSV/JSON | Plain text/code preview |
| DOCX | Extracted text and metadata first |
| XLSX/XLSM | Metadata and open/download link first; sheet preview later |
| MOV/video | Metadata and open/download link |
| PUB/unsupported | Metadata and defer-technical action |

Actions from file drawer: view original file, view extracted OCR/text, view latest pipeline result, add to review, run single-file pipeline, open raw source path.

### `/runs`

Purpose: Start and monitor predefined pipeline runs.

Main layout: Preset cards → Run history table → Selected run detail.

Run presets:

| Preset | Purpose |
|---|---|
| `qa_samples_full` | Full QA sample, LLM tags, OCR fallback, semantic examples |
| `qa_samples_fast` | QA sample without LLM tags for fast regression checks |
| `ocr_fallback_focus` | OCR-heavy sample with fallback enabled |
| `review_required_rerun` | Rerun files currently open in review queue |
| `random_route_candidate_audit` | Random sample of auto-accepted route candidates |
| `single_file_debug` | One selected file from browser/review row |

Run statuses: `queued` → `running` → `succeeded` / `failed` / `cancelled`.

Run actions: start, cancel, import results, rerun failed, open output directory, compare to previous run.

**Per-run report** (replaces standalone Reports page): works for both active and completed runs. Active: shows live progress, live log events, partial artifact counts, accumulated model usage. Completed: becomes the durable audit report. Must show provider, model, call count, input/output tokens, model runtime, cost (for external paid models), failures, and retries.

Run detail tabs: `Summary`, `Events`, `Files`, `Review Queue`, `Diff vs Previous`, `Artifacts`.

**Run lineage requirement:** Every review item must expose the run id/run key that produced it, and the run report must be one click away from every review row.

### `/golden-labels`

Purpose: Manage training/evaluation examples used by semantic tagging.

Capabilities: list labels, filter by correct primary tag/secondary tag/reviewer/source collection/last updated, edit primary tag/secondary tags/notes/reviewer, delete bad labels, show proposed-vs-correct mismatch, trigger semantic index rebuild, show semantic index status.

### `/semantic-index`

Purpose: Make retrieval evidence inspectable.

Capabilities: show index size/model/dimensions/created/updated, search labels by free text, show nearest labeled examples for a selected review item, show embedding provider/model status, flag labels with empty/weak snippets.

### `/reports`

Purpose: Measure whether the pipeline is improving.

Reports: review volume by reason, OCR quality summary, tag distribution, placement status summary, golden-label coverage by primary tag, semantic eval (primary accuracy, secondary precision/recall, confusion pairs, review rate, auto-accept precision, mismatch queue), run-to-run comparison (changed classifications/tags/routes, new failures, fixed failures).

## Backend API Structure

### Routers

| File | Purpose |
|---|---|
| `routers/health.py` | `/healthz`, `/admin/system/local-infrastructure` |
| `routers/pipeline.py` | `POST /admin/pipeline/run-file`, import LangGraph output |
| `routers/review.py` | Review queue, decisions, golden labels, placement report, review export |
| `routers/files.py` | File browser, file inspection, preview/text, add-to-review, single-file runs |
| `routers/runs.py` | Run presets, run lifecycle, progress, artifacts/results/report, cancellation, import, rerun failed |
| `routers/semantic.py` | Semantic index status, build, eval |

### Services

| File | Purpose |
|---|---|
| `services/run_commands.py` | Build commands for batch and single-file LangGraph runs |
| `services/run_execution.py` | Subprocess lifecycle and live run log/progress streaming |
| `services/run_reports.py` | Run progress/result/report/diff helpers |
| `services/model_usage.py` | Model usage artifact parsing and cost/runtime summaries |
| `services/semantic.py` | Semantic index status helper |

### Key API Endpoints

```
GET  /admin/files
GET  /admin/files/{file_id}
GET  /admin/files/{file_id}/preview
GET  /admin/files/{file_id}/text
POST /admin/files/{file_id}/run
POST /admin/files/{file_id}/add-to-review

GET  /admin/review/summary
GET  /admin/review/items
GET  /admin/review/items/{item_id}
GET  /admin/review/items/{item_id}/file
GET  /admin/review/items/{item_id}/text
GET  /admin/review/items/{item_id}/neighbors
POST /admin/review/items/{item_id}/decision
POST /admin/review/items/{item_id}/assign
POST /admin/review/import-langgraph-output

GET  /admin/runs/presets
POST /admin/runs
GET  /admin/runs/{run_id}
GET  /admin/runs/{run_id}/events
GET  /admin/runs/{run_id}/results
GET  /admin/runs/{run_id}/report
POST /admin/runs/{run_id}/cancel
POST /admin/runs/{run_id}/import-results
POST /admin/runs/{run_id}/rerun-failed

GET  /admin/semantic-index/status
POST /admin/semantic-index/build
GET  /admin/semantic-eval/latest
POST /admin/semantic-eval/run
```

## Backend LangGraph Structure

Target module layout (post-refactor):

| File | Purpose |
|---|---|
| `langgraph_pipeline.py` | Compatibility wrapper and CLI entry point; re-exports public functions |
| `graph/state.py` | `DocumentPipelineState`, `DocumentPipelineDeps` |
| `graph/runtime.py` | Single-file graph runner, dependency resolution |
| `graph/build.py` | Graph topology only (`build_document_graph`) |
| `graph/nodes.py` | Graph node implementations |
| `graph/batch.py` | Batch runner and aggregate artifact writer |
| `graph/cli.py` | CLI parsing and `python -m sunshine_extraction.langgraph_pipeline` behavior |

Every Python file must start with a module docstring explaining: what the file owns, what it does not own, and the main public functions/classes.

## SQLite Data Model (Operational Store)

```text
file_index         - searchable list of files known to the dashboard
pipeline_results   - per-file pipeline result rows
review_items       - review queue with decision workflow state
golden_labels      - trusted examples for semantic tagging
pipeline_runs      - dashboard-triggered run records with status and metadata
pipeline_run_events - visible run log and progress timeline
```

`file_index` fields: `id`, `source_path` (unique), `relative_path`, `sample_path`, `filename`, `extension`, `mime_type`, `size_bytes`, `source_collection`, `source_mtime`, `content_class`, `latest_run_id`, `latest_result_json`, `created_at`, `updated_at`.

`pipeline_runs` fields: `id`, `run_key`, `preset_key`, `status`, `input_root`, `output_dir`, `command_json`, `enable_llm_tags`, `llm_tag_provider`, `ocr_fallback_provider`, `semantic_index_path`, `started_at`, `completed_at`, `processed_count`, `failed_count`, `review_required_count`, `route_candidate_count`, `summary_json`, `error`.

`review_items` extended fields: `destination_path`, `placement_status`, `placement_rule`, `placement_date_confidence`, `default_privacy`, `reviewer_role`, `review_stage`, `priority`, `assigned_reviewer`, `run_id`, `run_key`.

Review stages: `needs_ocr_review`, `needs_tag_review`, `needs_placement_review`, `needs_privacy_review`, `needs_technical_followup`, `ready_for_acceptance`, `resolved`.

## Background Run Model

Runs must **not** block HTTP requests.

Current implementation:
1. `POST /admin/runs` creates `pipeline_runs` row with `queued`.
2. API starts a local subprocess for the selected preset.
3. Status changes to `running`.
4. stdout/stderr and graph audit events written to `pipeline_run_events`.
5. On process exit, status becomes `succeeded` or `failed`.
6. Summary JSON read from output dir and stored in `pipeline_runs.summary_json`.
7. Dashboard polls `GET /admin/runs/{run_id}` every few seconds.

V2 also supports Temporal backend (see `runbook.md`). The `Execution backend` selector in the Runs page chooses between `subprocess` (default/development) and `temporal` (production-shaped).

## Frontend Structure

```text
apps/dashboard/app/
  layout.tsx
  review/page.tsx
  files/page.tsx
  runs/
    page.tsx
    [runId]/report/page.tsx
  golden-labels/page.tsx
  semantic-index/page.tsx
  reports/page.tsx

apps/dashboard/components/
  app-shell/         (AppSidebar, TopBar)
  data-table/        (DataTable, ColumnHeader, FacetedFilter)
  file-preview/      (FilePreviewDrawer, PdfPreview, ImagePreview, TextPreview, UnsupportedPreview)
  review/            (ReviewQueueTable, ReviewDetailDrawer, ReviewDecisionForm, TagEvidencePanel, PlacementPanel, GoldenExamplesPanel)
  runs/              (RunPresetList, RunStartDialog, RunHistoryTable, RunEventsTable, RunResultsTable)
  ui/                (shadcn components)

apps/dashboard/lib/
  api.ts
  query-client.ts
  types.ts
  filters.ts
  format.ts
```

## Safety Rules

Allowed: read files, preview files, run extraction/OCR/classification, write pipeline artifacts, write review decisions, write golden labels, propose destination paths.

**Not allowed in MVP:** move source files, delete files, overwrite original files, mutate Google Drive, auto-apply physical folder placement.

Any future file-moving workflow must require: dry run, manifest of proposed moves, conflict detection, rollback metadata, explicit approval.

## Verification Gates

After any backend refactor:
```bash
.venv/bin/python -m pytest -q
npm --workspace apps/dashboard run build
```

Runtime smoke:
```bash
curl http://127.0.0.1:8001/healthz
curl http://127.0.0.1:8001/admin/runs/presets
curl http://127.0.0.1:8001/admin/review/summary
curl http://127.0.0.1:8001/admin/files/search?limit=1
```
