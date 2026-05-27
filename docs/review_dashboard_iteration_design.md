# Review Dashboard Iteration Design

Last updated: 2026-05-27

## Executive Summary

The review dashboard should become the operating console for the Sunshine
pipeline. Right now, too much iteration still happens through terminal commands,
JSONL files, ad hoc CSV inspection, and manually opened source files. That is
slowing down the actual product loop:

```text
run pipeline -> inspect failures -> correct labels -> rebuild evidence -> rerun -> measure improvement
```

This milestone should build three dashboard capabilities:

1. A searchable file browser with in-browser preview and extracted text.
2. A refined review cycle that turns human corrections into golden labels.
3. Predefined batch runs that can be launched, monitored, imported, and compared
   from the UI.

The recommended stack is to keep the existing `Next.js + FastAPI + SQLite +
LangGraph` architecture and strengthen the dashboard with focused open-source
libraries:

- `shadcn/ui` for component primitives and app shell.
- `TanStack Table` for review/file/run result tables.
- `TanStack Query` for server-state fetching, mutations, polling, and cache
  invalidation.
- `TanStack Virtual` for large lists.
- `react-pdf-viewer` or direct `pdf.js` for PDF preview.
- Native image/text preview first; add `OpenSeadragon` only when scanned pages
  need deep zoom.

Do not migrate to a full admin framework yet. `Refine`, `react-admin`, and AG
Grid are good tools, but the Sunshine dashboard is not a normal CRUD admin app.
The hard part is document preview, OCR comparison, semantic label review,
pipeline runs, and auditability. A focused Next dashboard is the lower-risk
choice.

## Current State

Already present:

- Next dashboard app in `apps/dashboard`.
- FastAPI admin API in `apps/api`.
- SQLite review store.
- Review queue page.
- File browser page.
- Runs page.
- Golden labels page.
- Reports page.
- LangGraph pipeline runner.
- OCR fallback and text quality validation.
- Semantic tagging evaluation work.

Current gaps:

- File browsing is not yet good enough to replace manual path inspection.
- Review is still not a tight labeling workflow.
- Golden labels are not easy enough to create, edit, compare, and reuse.
- Batch runs exist conceptually, but need a cleaner dashboard-driven control
  loop.
- Preview needs to show original file, extracted OCR/text, proposed tags,
  evidence, placement, warnings, and raw JSON in one place.
- The dashboard needs better run-to-run comparison so incorrect classifications
  become visible quickly.

## Product Goals

### Goal 1: File Browser

Users should be able to find and inspect files without using the terminal.

Required capabilities:

- Search by filename, source path, relative path, extension, tag, class, OCR
  text snippet, warning, and route status.
- Filter by source collection, file type, content class, primary tag, secondary
  tag, OCR quality, review state, privacy state, and placement state.
- Preview common files in the dashboard:
  - PDF
  - image
  - OCR text
  - extracted text
  - JSON/raw result
  - unsupported-file metadata
- Trigger a single-file pipeline run.
- Add a file to a named review queue or batch.
- Show latest pipeline result and latest review decision for each file.

### Goal 2: Refined Review Cycle

Review should not be a one-off correction. It should create durable evidence the
pipeline can learn from.

Required capabilities:

- Stable review queues:
  - OCR poor/empty/gibberish
  - tag disagreement
  - low confidence
  - route candidate random sample
  - placement missing or weak date
  - privacy-sensitive
  - technical defer
  - failed extraction
- Side-by-side review workspace:
  - source preview
  - OCR/extracted text
  - proposed class
  - proposed primary and secondary tags
  - destination/placement proposal
  - confidence and warnings
  - nearest golden labels
  - competing tag candidates
  - raw JSON
- Review actions:
  - accept
  - change class
  - change primary tag
  - change secondary tags
  - change placement year/date
  - change privacy state
  - defer OCR
  - defer technical issue
  - ignore
  - mark duplicate
- Every correction can become a golden label.
- Every decision records reviewer, timestamp, previous value, corrected value,
  notes, and source evidence.

### Goal 3: Predefined Batch Runs

Users should be able to run meaningful pipeline slices from the dashboard.

Required capabilities:

- Start predefined batches without remembering CLI commands.
- Run one file through the same graph as a batch file.
- Show run status, events, counts, failures, and output paths.
- Import completed results into the review DB.
- Compare a new run against a previous run.
- Link a run directly to its review queue.

Initial batch presets:

| Preset | Purpose |
|---|---|
| `qa_samples_all` | Full QA sample through LangGraph. |
| `qa_samples_fast_no_llm` | Fast deterministic/OCR sanity pass. |
| `qa_samples_llm_tags` | QA sample with structured LLM tag judgment. |
| `qa_samples_ocr_fallback` | OCR-heavy batch with local OCR and fallback OCR. |
| `accepted_route_candidate_sample` | Random precision audit of auto-routed files. |
| `review_required_only` | Rerun current review-required files after pipeline changes. |
| `single_file_debug` | One selected file through the production graph. |

## Framework Review

### Recommended Stack

| Need | Framework | Decision |
|---|---|---|
| Dashboard framework | Existing Next.js app router | Keep. Already in repo and fits custom workflow UI. |
| Component system | `shadcn/ui` | Use for shell, forms, tables, drawers, dialogs, tabs, badges, command palette, sidebar, tooltips, and toasts. |
| Tables | `@tanstack/react-table` | Use for review queue, file browser, run results, golden labels, and reports. |
| API state | `@tanstack/react-query` | Use for fetches, mutations, polling run events, optimistic updates, and cache invalidation. |
| Large lists | `@tanstack/react-virtual` | Use once file/result lists grow beyond a few hundred visible rows. |
| Forms | `react-hook-form` + `zod` | Use for review decisions, run presets, filters, and label correction forms. |
| PDF preview | `react-pdf-viewer` first, direct `pdf.js` if needed | Use for PDF page navigation and browser preview. |
| Image preview | Native image viewer first | Add zoom/rotate/fit. Use `OpenSeadragon` later for large scans. |
| Charts | shadcn chart patterns or `recharts` | Use for review volume, tag accuracy, OCR quality, run comparisons. |

### Why shadcn/ui

shadcn/ui is a good fit because it provides component source we own rather than
a closed visual framework. The project needs a dense operational tool, and we
will likely tune tables, drawers, badges, and forms to the archive workflow.
The docs include dashboard-relevant primitives such as sidebar, data table,
drawer/sheet, command, dialog, form, scroll area, tabs, tooltip, and toast.

### Why TanStack Table

The dashboard needs table behavior that should not be hand-rolled:

- sorting
- column filters
- global search
- column visibility
- row selection
- expandable rows
- custom tag/status cells
- pagination or virtualized scrolling

TanStack Table is headless, which lets us keep the Sunshine-specific visual
design while using a battle-tested table state engine.

### Why TanStack Query

This app is server-state heavy:

- review decisions mutate rows
- run events need polling
- imported runs invalidate review/file/report summaries
- semantic index rebuilds invalidate nearest-neighbor evidence
- filters map to API queries

TanStack Query gives one consistent model for loading, error, mutation, polling,
and cache invalidation.

### Why Not Refine or react-admin Now

Refine and react-admin make sense for CRUD-heavy internal tools. This app is a
custom document review workbench. The hard screens are not `list/create/edit`
forms; they are file preview, OCR comparison, semantic evidence, review
decisions, run monitoring, and evaluation reports.

Reconsider Refine only if we later need many generic CRUD resources, auth/roles,
or generated resource pages. Reconsider AG Grid only if TanStack Table cannot
handle performance or table feature requirements.

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

## Page Design

### `/review`

Purpose: Resolve uncertain or audited pipeline results.

Main layout:

```text
Filter bar
Review table
Right-side detail pane/drawer
```

Table columns:

- filename
- source collection
- content class
- primary tag
- secondary tags
- confidence
- OCR quality
- placement status
- privacy state
- route status
- review reason
- warning chips
- latest reviewer

Detail tabs:

- `Preview`: PDF/image/file preview.
- `Text`: OCR/extracted text with page/chunk metadata.
- `Tagging`: proposed tag, competing tags, nearest labels, LLM evidence.
- `Placement`: folder rule, proposed path, date evidence, privacy default.
- `History`: previous runs and review decisions.
- `Raw`: source JSON for debugging.

Success criteria:

- A reviewer can resolve a row without opening terminal output.
- Accept/change/defer actions update the table without full page reload.
- The next review item is easy to move to.
- Saving a correction updates golden-label counts.

### `/files`

Purpose: Search and inspect corpus files directly.

Main layout:

```text
Search/filter toolbar
File table
Preview drawer
```

Required filters:

- `q`
- extension
- content class
- source collection
- primary tag
- secondary tag
- OCR quality
- latest run status
- review state
- placement state

Preview behavior:

| Type | Behavior |
|---|---|
| PDF | Browser PDF viewer with extracted text beside it. |
| JPG/PNG/TIF-derived | Fit/zoom/rotate image preview. |
| TXT/MD/CSV/JSON | Plain text/code preview. |
| DOCX | Extracted text and metadata first. Native render later. |
| XLSX/XLSM | Metadata and open/download link first. Sheet preview later. |
| MOV/video | Metadata and open/download link. |
| PUB/unsupported | Metadata and defer-technical action. |

Success criteria:

- Searching `1992-1993.pdf` finds the file and latest pipeline result.
- A scanned PDF can be previewed next to OCR text.
- A selected file can be sent through `single_file_debug`.
- Unsupported files are understandable and not silently failed.

### `/runs`

Purpose: Start and monitor predefined pipeline runs.

Main layout:

```text
Preset cards
Run history table
Selected run detail
```

Run detail tabs:

- `Summary`
- `Events`
- `Files`
- `Review Queue`
- `Diff vs Previous`
- `Artifacts`

Success criteria:

- User can start `qa_samples_llm_tags` from the dashboard.
- Run status changes from queued to running to succeeded/failed.
- Run events are visible while the process runs.
- Completed results can be imported from the dashboard.
- The run links to the review queue created by that import.

### `/golden-labels`

Purpose: Manage trusted examples used by semantic tagging.

Capabilities:

- List labels.
- Filter by correct primary tag, secondary tag, reviewer, source collection,
  and last updated.
- Edit primary tag, secondary tags, notes, and reviewer.
- Delete bad labels.
- Show proposed-vs-correct mismatch.
- Trigger semantic index rebuild.
- Show semantic index status.

Success criteria:

- A human correction can be turned into a reusable label.
- Bad labels can be fixed without direct SQLite edits.
- Semantic index rebuild is visible and auditable.

### `/semantic-index`

Purpose: Make retrieval evidence inspectable.

Capabilities:

- Show index size, model, dimensions, created/updated time.
- Search labels by free text.
- Show nearest labeled examples for a selected review item.
- Show embedding provider/model status.
- Flag labels with empty/weak snippets.

Success criteria:

- User can see whether embeddings are actually being used.
- User can inspect why a tag was proposed based on nearest examples.
- Empty or bad labels are visible.

### `/reports`

Purpose: Measure whether the pipeline is improving.

Reports:

- Review volume by reason.
- OCR quality summary.
- Tag distribution.
- Placement status summary.
- Golden-label coverage by primary tag.
- Semantic eval report:
  - primary accuracy
  - secondary precision/recall
  - confusion pairs
  - review rate
  - auto-accept precision
  - mismatch queue
- Run-to-run comparison:
  - changed classifications
  - changed tags
  - changed routes
  - new failures
  - fixed failures

Success criteria:

- The dashboard answers: “Did this pipeline change improve the sample?”
- The dashboard identifies which tags are confused.
- The dashboard shows whether review-required volume is going down for the right
  reason, not because bad items are being auto-accepted.

## Backend Implementation

### Tables

Keep SQLite for this milestone. It is enough for local review, single-user
iteration, and artifact-backed auditability.

Required tables:

```text
file_index
pipeline_results
review_items
golden_labels
pipeline_runs
pipeline_run_events
```

`file_index` should contain:

- `id`
- `source_path`
- `relative_path`
- `sample_path`
- `filename`
- `extension`
- `mime_type`
- `size_bytes`
- `source_collection`
- `source_mtime`
- `content_class`
- `latest_run_id`
- `latest_result_json`
- `created_at`
- `updated_at`

`pipeline_runs` should contain:

- `id`
- `run_key`
- `preset_key`
- `status`
- `input_root`
- `output_dir`
- `command_json`
- `enable_llm_tags`
- `llm_tag_provider`
- `ocr_fallback_provider`
- `semantic_index_path`
- `started_at`
- `completed_at`
- `processed_count`
- `failed_count`
- `review_required_count`
- `route_candidate_count`
- `summary_json`
- `error`

`pipeline_run_events` should contain:

- `id`
- `run_id`
- `timestamp`
- `level`
- `node`
- `source_path`
- `message`
- `payload_json`

### API Endpoints

File browser:

```text
GET  /admin/files
GET  /admin/files/{file_id}
GET  /admin/files/{file_id}/preview
GET  /admin/files/{file_id}/text
POST /admin/files/{file_id}/run
POST /admin/files/{file_id}/add-to-review
```

Review:

```text
GET  /admin/review/items
GET  /admin/review/items/{item_id}
GET  /admin/review/items/{item_id}/file
GET  /admin/review/items/{item_id}/text
GET  /admin/review/items/{item_id}/neighbors
POST /admin/review/items/{item_id}/decision
POST /admin/review/import-langgraph-output
```

Golden labels:

```text
GET    /admin/review/golden-labels
PATCH  /admin/review/golden-labels/{label_id}
DELETE /admin/review/golden-labels/{label_id}
GET    /admin/review/golden-label-summary
```

Runs:

```text
GET  /admin/runs/presets
POST /admin/runs
GET  /admin/runs
GET  /admin/runs/{run_id}
GET  /admin/runs/{run_id}/events
GET  /admin/runs/{run_id}/results
POST /admin/runs/{run_id}/cancel
POST /admin/runs/{run_id}/import-results
POST /admin/runs/{run_id}/rerun-failed
```

Semantic index and evaluation:

```text
GET  /admin/semantic-index/status
POST /admin/semantic-index/build
POST /admin/semantic-index/search
GET  /admin/semantic-eval/latest
POST /admin/semantic-eval/run
```

### Background Run Model

Runs must not block HTTP requests.

Recommended first implementation:

1. API inserts `pipeline_runs` row with `queued`.
2. API starts a local subprocess for the selected preset.
3. Runner writes line-oriented events and final artifacts.
4. API records status and summary.
5. Dashboard polls run status/events using TanStack Query.
6. User imports completed results into review DB.

Later upgrade path:

- local subprocess
- RQ/Celery
- Temporal
- hosted job runner

Do not start with Temporal. It is likely too heavy until the local product loop
is proven.

## Frontend Implementation

Recommended structure:

```text
apps/dashboard/app/
  layout.tsx
  review/page.tsx
  files/page.tsx
  runs/page.tsx
  golden-labels/page.tsx
  semantic-index/page.tsx
  reports/page.tsx

apps/dashboard/components/
  app-shell/
  data-table/
  file-preview/
  review/
  runs/
  labels/
  reports/
  ui/

apps/dashboard/lib/
  api.ts
  query-client.ts
  types.ts
  filters.ts
```

Implementation notes:

- Use client components for pages with filters, preview drawers, mutations, and
  run polling.
- Keep API request helpers in `lib/api.ts`.
- Keep shared response types in `lib/types.ts`.
- Use URL query params for durable filters where possible.
- Use drawer/sheet for selected-item detail so tables remain readable.
- Do not put form controls in every table row.
- Use badges for route status, quality, confidence band, warnings, and privacy.

## Review Data Contract

Each review item should expose enough information to judge the decision without
opening raw artifacts:

```json
{
  "id": 123,
  "source_path": "...",
  "relative_path": "...",
  "sample_path": "...",
  "content_class": "scanned_document",
  "primary_tag": "history_archive_general",
  "secondary_tags": ["founders", "club_history"],
  "confidence": 0.82,
  "quality": "ok",
  "ocr_text_snippet": "...",
  "placement": {
    "status": "proposed",
    "folder": "06_History_Archive",
    "rule": "by_year",
    "year": 1992,
    "date_confidence": 0.76
  },
  "evidence": {
    "llm": {},
    "deterministic": {},
    "semantic_neighbors": []
  },
  "warnings": [],
  "latest_review": {}
}
```

## Safety Rules

Allowed in this milestone:

- read files
- preview files
- run extraction/OCR/classification
- write pipeline artifacts
- write review decisions
- write golden labels
- propose destination paths

Not allowed in this milestone:

- move source files
- delete files
- overwrite original files
- mutate Google Drive
- auto-apply physical folder placement

Any future file-moving workflow must be separate and require:

- dry run
- manifest of proposed moves
- conflict detection
- rollback metadata
- explicit approval

## Implementation Phases

### Phase 1: Review Workspace Upgrade

Implementation:

- Convert review table to reusable TanStack Table component.
- Add drawer/detail pane.
- Move review form into detail pane.
- Add text preview, tag evidence, warnings, placement, and raw JSON tabs.
- Add mutation-driven accept/change/defer flow.
- Add save-as-golden-label option.

Success criteria:

- Reviewer can inspect and resolve rows without terminal usage.
- Review decision updates the UI immediately.
- Golden-label count changes after saving a label.
- Table filters work for class, tag, quality, route status, and review reason.

### Phase 2: File Browser

Implementation:

- Build `file_index` population from imported results and QA sample scans.
- Add `/files` search/filter API.
- Add file preview endpoints.
- Add PDF/image/text preview drawer.
- Add single-file run action.

Success criteria:

- User can search by filename/path/tag/snippet.
- User can preview a PDF or image and compare extracted text.
- User can run one selected file through the graph.
- Unsupported files show a clear technical defer path.

### Phase 3: Batch Runs

Implementation:

- Add preset registry.
- Add `pipeline_runs` and `pipeline_run_events`.
- Add `/runs` page.
- Start run as background subprocess.
- Poll events/status.
- Import completed run output into review DB.

Success criteria:

- User can start a QA batch from the dashboard.
- Status and events are visible while running.
- Failed runs preserve error details.
- Completed runs can be imported and linked to review.

### Phase 4: Golden Labels and Semantic Index

Implementation:

- Add edit/delete for golden labels.
- Add semantic index status/build page.
- Add nearest-neighbor search endpoint.
- Show neighbors in review detail.
- Add semantic eval run/report actions.

Success criteria:

- User can create, edit, and delete labels without SQLite.
- User can rebuild semantic index from UI.
- Review detail shows nearest trusted examples.
- Eval report shows accuracy, confusion pairs, and mismatch rows.

### Phase 5: Run Comparison and QA Reports

Implementation:

- Store run comparison summaries.
- Add report filters by run, preset, tag, class, and quality.
- Add changed-result queues.
- Add export CSV/JSON for review packets.

Success criteria:

- User can compare two runs and see changed tags/classes/routes.
- The dashboard identifies regressions.
- A review packet can be exported for customer-facing audit.

## Milestone Acceptance Criteria

This milestone is complete when:

- The file browser can search, filter, and preview representative source files.
- The review page supports fast accept/change/defer decisions.
- Review corrections can create and update golden labels.
- Predefined runs can be started from the dashboard.
- Run status/events are visible without terminal access.
- Completed run results can be imported into the review DB.
- Semantic index status and rebuild are visible.
- Reports show OCR quality, review volume, tag distribution, semantic eval
  metrics, and run-to-run changes.
- All new API behavior has focused tests.
- Dashboard production build passes.
- No source files are moved, deleted, or overwritten.

## First Implementation Slice

Build this in order:

1. Create shared dashboard UI primitives:
   - data table
   - filter toolbar
   - detail drawer
   - status badges
   - preview frame
2. Upgrade `/review` to the new workspace.
3. Add missing review/golden-label API mutations.
4. Upgrade `/files` preview and search.
5. Add run preset execution and event polling.
6. Add semantic index status/build and semantic eval report actions.
7. Add tests and run dashboard build.

This order improves daily review immediately while creating reusable components
for the file browser and run workflow.

## Source Review

The framework choices above are based on the current repo shape plus current
open-source project documentation:

- shadcn/ui documents composable app/dashboard primitives including data table
  and sidebar: https://ui.shadcn.com/docs
- TanStack Table is a headless table engine for React and other UI frameworks:
  https://tanstack.com/table
- TanStack Query is the maintained React server-state library for fetching,
  mutation, polling, and invalidation: https://tanstack.com/query/latest/docs/react
- React PDF Viewer provides a React PDF viewing layer suitable for embedded
  document preview: https://react-pdf-viewer.dev/docs
- OpenSeadragon is appropriate for deep zoom/pan over large image scans:
  https://openseadragon.github.io
- Refine is a strong CRUD/internal-tool framework but should be held in reserve
  until the app becomes more resource-admin-heavy: https://refine.dev/docs
- AG Grid Community is a capable data grid, but TanStack Table is a better
  first fit because this dashboard needs custom workflow composition more than a
  spreadsheet-like grid: https://www.ag-grid.com/react-data-grid
