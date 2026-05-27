# Review Dashboard Implementation Design

Last updated: 2026-05-26

## Executive Summary

The next product milestone is to turn the Sunshine review dashboard into the
operating console for file inspection, review, training, and batch iteration.

The current dashboard proves the review loop can exist, but it is still too
flat: one large table, row-level forms, limited file preview, no first-class file
browser, and no UI-driven batch runs. The next version should be built as a
workflow application with three primary surfaces:

1. `Review`: inspect pipeline decisions and create golden labels.
2. `Files`: search, filter, preview, and run individual files.
3. `Runs`: launch predefined batches, monitor progress, import results, and
   compare outcomes.

The recommended implementation keeps the current `Next.js + FastAPI + SQLite +
LangGraph` architecture and adds proven open-source UI libraries:

- `shadcn/ui` for the app shell and component system.
- `TanStack Table` for dense, filterable, review-oriented tables.
- `TanStack Query` for API state, mutations, polling, and cache invalidation.
- `TanStack Virtual` for large file and result lists.
- `react-pdf-viewer` or direct `pdf.js` for PDF preview.
- Browser-native image/text preview first, with `OpenSeadragon` later for large
  scanned images and scrapbook pages.

Do not adopt a full admin framework yet. `Refine` and `react-admin` are useful
for CRUD-heavy back offices, but this dashboard is a custom document review
workbench. The highest-complexity UI is not CRUD; it is preview, OCR comparison,
tag/placement review, golden-label capture, and long-running batch runs.

## Goals

### Product Goals

- Make file inspection possible without terminal access.
- Make review decisions faster, cleaner, and reusable as training/evaluation
  labels.
- Make batch pipeline runs repeatable from the dashboard.
- Make pipeline errors visible and actionable.
- Make OCR, tag, placement, privacy, and evidence review happen in one place.
- Reduce JSONL/manual-command workflow during normal iteration.

### Engineering Goals

- Keep the current app architecture.
- Add reusable UI foundations before adding more one-off pages.
- Keep all file operations read-only except writing review/run artifacts.
- Treat long-running pipeline jobs as background jobs, not blocking HTTP
  requests.
- Store enough run/review metadata to compare pipeline changes over time.
- Keep APIs testable and small.

### Non-Goals

- Do not move files in Google Drive or on disk.
- Do not implement authentication/roles in this milestone.
- Do not build a generic cloud file manager.
- Do not replace LangGraph.
- Do not migrate to a full CRUD admin framework unless later evidence demands
  it.

## Framework Decision

### Chosen Stack

| Layer | Choice | Role |
|---|---|---|
| App framework | Existing Next.js app router | Dashboard frontend. |
| API | Existing FastAPI app | Admin endpoints, review DB, file preview, batch control. |
| UI components | `shadcn/ui` | App shell, forms, dialogs, drawers, tabs, badges, sidebar. |
| Tables | `@tanstack/react-table` | Review queue, file browser, run results, golden labels. |
| API state | `@tanstack/react-query` | Fetching, mutations, polling runs, invalidating summaries. |
| Large lists | `@tanstack/react-virtual` | Fast scrolling for file/result tables. |
| Forms | `react-hook-form` + `zod` | Review decisions, run presets, filters, corrections. |
| PDF preview | `react-pdf-viewer` or `pdf.js` | Browser PDF viewing and page navigation. |
| Images | Native image preview first | Fit, zoom, rotate; add OpenSeadragon later if needed. |
| Charts | `recharts` or shadcn charts | Review/run summaries and evaluation reports. |

### Why shadcn/ui

`shadcn/ui` is not a closed component package. Its model is to add component
source code directly into the app, which fits this project because we need a
custom operational UI and we will likely tune components heavily. Its component
catalog includes the primitives this dashboard needs: sidebar, tabs, data table,
drawer/sheet, dialogs, command palette, badges, forms, inputs, scroll areas,
toasts, and tooltips.

### Why TanStack Table

The review dashboard needs table behavior that plain HTML tables should not
own:

- column filters
- global search
- sorting
- column visibility
- row selection
- pagination or virtualized scrolling
- expandable rows
- custom cells for tags, confidence, route status, warnings, and actions

TanStack Table is headless, so it gives us table state and behavior without
forcing a visual style.

### Why TanStack Query

The dashboard is server-state heavy:

- review decisions mutate records
- golden labels update counts
- batch runs need polling
- result imports invalidate summaries
- file search depends on filters
- run events stream or poll over time

TanStack Query avoids hand-rolled loading/error/cache logic and gives a clean
pattern for mutations and refetching.

### Why Not Refine or react-admin Yet

`Refine` and `react-admin` are strong open-source admin frameworks, but they are
best when the application is primarily CRUD over resources. The Sunshine
dashboard is a workflow console:

- document preview matters as much as editing
- review is state-machine-like, not simple update forms
- pipeline runs are background jobs
- OCR/tag/placement evidence need custom layouts
- file safety is domain-specific

Adopt a full admin framework only if the dashboard later becomes mostly user,
document, label, run, and report CRUD.

## Product Architecture

```text
Next.js Dashboard
  /review
  /files
  /runs
  /golden-labels
  /reports
      |
      v
FastAPI Admin API
  review endpoints
  file search/preview endpoints
  run preset/run status endpoints
  artifact endpoints
      |
      v
SQLite Operational Store
  pipeline_results
  review_items
  golden_labels
  file_index
  pipeline_runs
  pipeline_run_events
      |
      v
LangGraph Pipeline Runner
  single-file runs
  predefined batch runs
  artifact generation
```

## User Workflows

### Workflow 1: Review a Pipeline Result

1. User opens `/review`.
2. User filters to a queue, such as `OCR poor`, `placement missing date`, or
   `tag disagreement`.
3. User selects a row.
4. Detail drawer opens with:
   - file preview
   - OCR/extracted text
   - proposed class
   - proposed primary/secondary tags
   - destination path
   - placement status and date evidence
   - nearest golden examples
   - competing tags
   - warnings
   - raw JSON tab
5. User accepts, changes, defers, ignores, or marks duplicate.
6. Decision updates the DB.
7. If enabled, decision creates or updates a golden label.
8. UI moves to next item without a full page reload.

### Workflow 2: Search and Inspect a File

1. User opens `/files`.
2. User searches by filename, path, tag, date, source collection, or text
   snippet.
3. User selects a file.
4. Preview drawer opens.
5. User can:
   - view original file
   - view extracted OCR/text
   - view latest pipeline result
   - add to review
   - run single-file pipeline
   - open raw source path if supported

### Workflow 3: Trigger a Batch Run

1. User opens `/runs`.
2. User chooses a preset, such as `QA samples full pipeline`.
3. User confirms parameters.
4. API creates a run row and starts a background process.
5. Dashboard polls run status and events.
6. User sees progress, failures, and output paths.
7. When complete, user imports results into review DB.
8. Dashboard links to filtered review queue for that run.

### Workflow 4: Train and Evaluate

1. User reviews files and creates golden labels.
2. User opens `/golden-labels`.
3. User reviews label coverage by primary tag and source type.
4. User rebuilds semantic index.
5. User reruns a QA batch.
6. User opens `/reports`.
7. User inspects accuracy, mismatches, confusion pairs, and review rate.

## Page Design

### App Shell

Navigation:

```text
Review
Files
Runs
Golden Labels
Reports
Settings
```

Use a dense operational style:

- left sidebar
- top filter/action bar
- table/list main pane
- right detail drawer or split pane
- no marketing hero sections
- no card-heavy decorative layout

### `/review`

Primary purpose: resolve review items and create golden labels.

Components:

- `ReviewFilters`
- `ReviewQueueTable`
- `ReviewDetailDrawer`
- `FilePreviewPanel`
- `ExtractedTextPanel`
- `TagEvidencePanel`
- `PlacementPanel`
- `GoldenExamplePanel`
- `ReviewDecisionForm`

Table columns:

- filename
- route/review reason
- content class
- proposed primary tag
- secondary tags
- destination path
- placement status
- OCR quality
- confidence
- warning count
- review status
- updated at

Default filters:

- status: `open`
- route status
- review reason
- primary tag
- content class
- quality
- placement status
- warning type
- source collection

Detail tabs:

- `Preview`
- `OCR/Text`
- `Tagging`
- `Placement`
- `Examples`
- `Raw JSON`

Review actions:

- `Accept`
- `Change`
- `Defer`
- `Ignore`
- `Duplicate`
- `Next`

### `/files`

Primary purpose: search and inspect files independent of review queue.

Components:

- `FileSearchBar`
- `FileFacetFilters`
- `FileTable`
- `FilePreviewDrawer`
- `SingleFileRunDialog`

Search fields:

- filename
- relative path
- source path
- extension
- source collection
- current content class
- latest primary tag
- latest destination path
- review status
- OCR text snippet

Preview tabs:

- `Preview`
- `Extracted Text`
- `Latest Result`
- `Runs`
- `Raw Metadata`

Supported preview types:

| File type | V1 preview behavior |
|---|---|
| PDF | embedded PDF viewer plus extracted text panel |
| JPG/PNG/JPEG | image preview with fit/zoom/rotate |
| TIF/TIFF | convert/render preview later; V1 may use file open link plus OCR text |
| TXT/MD/CSV/JSON | text preview |
| DOCX | extracted text preview, raw file open link |
| XLSX/XLSM | metadata/open link first, table preview later |
| MOV/MP4 | metadata/open link first |
| PUB/unknown | metadata and defer technical action |

### `/runs`

Primary purpose: start and monitor pipeline runs.

Components:

- `RunPresetList`
- `RunStartDialog`
- `RunHistoryTable`
- `RunStatusPanel`
- `RunEventsTable`
- `RunResultsTable`

Run presets:

| Preset key | Description |
|---|---|
| `qa_samples_full` | Full QA sample, LLM tags, OCR fallback, semantic examples. |
| `qa_samples_fast` | QA sample without LLM tags for fast regression checks. |
| `ocr_fallback_focus` | OCR-heavy sample with fallback enabled. |
| `review_required_rerun` | Rerun files currently open in review queue. |
| `random_route_candidate_audit` | Random sample of auto-accepted route candidates. |
| `single_file_debug` | One selected file from browser/review row. |

Run statuses:

- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`

Run actions:

- start
- cancel
- import results
- rerun failed
- open output directory
- compare to previous run

### `/golden-labels`

Primary purpose: manage training/evaluation examples.

Views:

- label table
- coverage summary
- primary tag distribution
- secondary tag distribution
- stale labels
- labels with changed pipeline predictions

Actions:

- edit label
- delete label from golden set
- rebuild semantic index
- run semantic eval
- open source file

### `/reports`

Primary purpose: understand whether changes improve the pipeline.

Reports:

- latest run summary
- primary tag accuracy
- secondary precision/recall
- confusion matrix
- review rate
- auto-accept precision
- OCR quality distribution
- placement resolution rate
- missing-date queue
- mismatches by tag

## Data Model

### Existing Tables to Keep

- `pipeline_results`
- `review_items`
- `golden_labels`

### Add `file_index`

Purpose: searchable list of files known to the dashboard.

Fields:

```text
id integer primary key
source_path text unique
relative_path text
sample_path text
filename text
extension text
mime_type text
size_bytes integer
source_collection text
source_mtime text
content_class text
latest_run_id integer
latest_result_json text
created_at text
updated_at text
```

Population sources:

- imported pipeline outputs
- QA sample folders
- manifest import
- single-file run results

### Add `pipeline_runs`

Purpose: track dashboard-triggered runs.

Fields:

```text
id integer primary key
run_key text unique
preset_key text
status text
input_root text
output_dir text
command_json text
enable_llm_tags integer
llm_tag_provider text
ocr_fallback_provider text
semantic_index_path text
started_at text
completed_at text
processed_count integer
route_candidate_count integer
review_required_count integer
failed_count integer
summary_json text
error text
created_at text
updated_at text
```

### Add `pipeline_run_events`

Purpose: visible run log and progress timeline.

Fields:

```text
id integer primary key
run_id integer
timestamp text
level text
node text
source_path text
relative_path text
message text
payload_json text
```

### Evolve `review_items`

Add or derive:

```text
destination_path
placement_status
placement_rule
placement_date_confidence
default_privacy
reviewer_role
review_stage
priority
assigned_reviewer
```

Review stages:

- `needs_ocr_review`
- `needs_tag_review`
- `needs_placement_review`
- `needs_privacy_review`
- `needs_technical_followup`
- `ready_for_acceptance`
- `resolved`

## API Design

### Files

```text
GET /admin/files
GET /admin/files/{file_id}
GET /admin/files/{file_id}/preview
GET /admin/files/{file_id}/text
POST /admin/files/{file_id}/run
POST /admin/files/{file_id}/review
```

`GET /admin/files` query parameters:

```text
q
source_collection
extension
content_class
primary_tag
route_status
review_status
placement_status
limit
cursor
```

### Review

```text
GET /admin/review/summary
GET /admin/review/items
GET /admin/review/items/{item_id}
GET /admin/review/items/{item_id}/file
GET /admin/review/items/{item_id}/text
GET /admin/review/items/{item_id}/neighbors
POST /admin/review/items/{item_id}/decision
POST /admin/review/items/{item_id}/assign
POST /admin/review/import-langgraph-output
```

Review decision payload:

```json
{
  "decision": "accept",
  "correct_class": "document",
  "correct_tag": "meeting_records",
  "correct_secondary_tags": ["meeting_minutes"],
  "correct_destination_path": "01_Governance_Admin/1992-1993",
  "correct_placement_year": "1992-1993",
  "correct_privacy": "club_internal",
  "review_stage": "resolved",
  "notes": "Looks correct.",
  "reviewer": "james",
  "save_as_golden": true
}
```

### Runs

```text
GET /admin/runs/presets
POST /admin/runs
GET /admin/runs
GET /admin/runs/{run_id}
GET /admin/runs/{run_id}/events
GET /admin/runs/{run_id}/results
POST /admin/runs/{run_id}/cancel
POST /admin/runs/{run_id}/import-results
POST /admin/runs/{run_id}/rerun-failed
```

Run start payload:

```json
{
  "preset_key": "qa_samples_full",
  "input_root": "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples",
  "output_dir": "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/dashboard-runs/qa_samples_full_2026-05-26T190000",
  "enable_llm_tags": true,
  "llm_tag_provider": "auto",
  "ocr_fallback_provider": "openai",
  "import_on_success": false
}
```

## Background Run Architecture

Do not run batch commands inside a blocking HTTP request.

Initial implementation:

1. `POST /admin/runs` creates `pipeline_runs` row with `queued`.
2. API starts a local subprocess with the selected preset command.
3. Status changes to `running`.
4. stdout/stderr and graph audit events are written to `pipeline_run_events`.
5. On process exit, status becomes `succeeded` or `failed`.
6. Summary JSON is read from output dir and stored in `pipeline_runs.summary_json`.
7. Dashboard polls `GET /admin/runs/{run_id}` every few seconds.

Later upgrade path:

- move run execution to RQ/Celery/Temporal if concurrent workloads grow
- add cancellation by process group
- add durable event streaming
- add user attribution when auth exists

## Frontend File Structure

```text
apps/dashboard/app/
  layout.tsx
  page.tsx
  review/page.tsx
  files/page.tsx
  runs/page.tsx
  golden-labels/page.tsx
  reports/page.tsx

apps/dashboard/components/
  app-shell/
    AppSidebar.tsx
    TopBar.tsx
  data-table/
    DataTable.tsx
    ColumnHeader.tsx
    FacetedFilter.tsx
  file-preview/
    FilePreviewDrawer.tsx
    PdfPreview.tsx
    ImagePreview.tsx
    TextPreview.tsx
    UnsupportedPreview.tsx
  review/
    ReviewQueueTable.tsx
    ReviewDetailDrawer.tsx
    ReviewDecisionForm.tsx
    TagEvidencePanel.tsx
    PlacementPanel.tsx
    GoldenExamplesPanel.tsx
  runs/
    RunPresetList.tsx
    RunStartDialog.tsx
    RunHistoryTable.tsx
    RunEventsTable.tsx
  ui/
    shadcn components

apps/dashboard/lib/
  api.ts
  query-client.tsx
  types.ts
  format.ts
```

## Implementation Plan

### Phase 1: UI Foundation and Review Redesign

Tasks:

1. Install/configure `shadcn/ui`.
2. Add required components:
   - button
   - badge
   - input
   - select
   - checkbox
   - tabs
   - sheet/drawer
   - dialog
   - table
   - sidebar
   - dropdown-menu
   - tooltip
   - scroll-area
   - sonner/toast
3. Add `@tanstack/react-table`.
4. Add `@tanstack/react-query`.
5. Create dashboard app shell with sidebar navigation.
6. Move current review dashboard to `/review`.
7. Replace current HTML table with TanStack Table.
8. Move review decision form into detail drawer.
9. Add placement fields to review UI.
10. Add API filters for review queue.

Success criteria:

- Review UI no longer relies on one giant row form.
- User can filter review items by status, tag, class, quality, route reason, and
  placement status.
- User can inspect file evidence and save a review decision from a drawer.
- Accept/change/defer mutation updates the table without a full page reload.
- Dashboard build passes.

### Phase 2: File Browser

Tasks:

1. Add `file_index` table.
2. Populate file index from imported results and QA samples.
3. Add file search API.
4. Add `/files` page.
5. Add searchable/filterable file table.
6. Add preview drawer.
7. Add PDF preview.
8. Add image preview.
9. Add text/OCR preview.
10. Add single-file run action.

Success criteria:

- User can search `1992-1993.pdf`.
- User can preview the source PDF or open it.
- User can view returned OCR text from the dashboard.
- User can trigger a single-file run for a selected file.
- Unsupported files show a technical-defer path instead of failing silently.

### Phase 3: Batch Runs

Tasks:

1. Add `pipeline_runs` and `pipeline_run_events`.
2. Define run preset registry.
3. Add run API endpoints.
4. Add subprocess runner.
5. Add run status polling.
6. Add `/runs` page.
7. Add run history table.
8. Add run event log.
9. Add import-results action.
10. Link completed run to filtered review queue.

Success criteria:

- User can launch `qa_samples_full` from dashboard.
- User can see queued/running/succeeded/failed states.
- User can inspect live or recent run events.
- User can import completed run results into review DB.
- Failed runs preserve error text and output path.

### Phase 4: Golden Labels and Semantic Index

Tasks:

1. Add `/golden-labels`.
2. Add golden label edit/delete endpoints.
3. Add coverage summaries.
4. Add semantic-index build action.
5. Add semantic-eval action.
6. Add eval report page.

Success criteria:

- User can see how many labels exist per primary tag.
- User can find underrepresented tags.
- User can rebuild semantic index from dashboard.
- User can run eval from dashboard.
- User can inspect mismatches and route them into review.

### Phase 5: Placement and Privacy Review

Tasks:

1. Add placement-specific filters.
2. Add placement correction fields.
3. Add privacy correction fields.
4. Store corrected destination/year/privacy in review decisions.
5. Add placement report.

Success criteria:

- Missing-date records are easy to find.
- User can correct placement year/range.
- Corrected placement is stored for later evaluation.
- Sensitive tags clearly show default privacy.
- No file is marked ready for move if placement status is unresolved.

## Success Criteria for the Whole Milestone

The milestone is complete when:

- Dashboard has `Review`, `Files`, and `Runs` pages.
- Review uses a proper table plus detail drawer.
- File browser can search, filter, and preview common files.
- Batch presets can be launched from the UI.
- Batch run status is visible without terminal access.
- Completed runs can be imported into the review DB.
- Review decisions can create golden labels.
- OCR text, tag evidence, nearest examples, competing tags, placement, and
  privacy are visible in one review surface.
- New backend endpoints have tests.
- Full Python test suite passes.
- Dashboard production build passes.
- No dashboard action moves/deletes source files.

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| File preview tries to support too much at once | Slows milestone | Start with PDF, image, text/OCR, unsupported fallback. |
| Batch runs block API worker | Dashboard hangs | Use subprocess/background runner and polling. |
| Tables become slow with large file lists | Bad UX | Use server-side filtering plus TanStack Virtual. |
| Review form gets too complex | Review friction | Use tabs and stage-specific fields; keep primary action obvious. |
| Golden labels become noisy | Training quality drops | Separate accept/change/defer and make save-as-golden explicit. |
| Placement corrections mix with tag corrections | Confusing labels | Store corrected tag and corrected placement separately. |
| UI framework churn | Lost time | Use shadcn/TanStack incrementally, not a full rewrite. |

## First Build Slice

Build this first:

1. Add shadcn/ui and TanStack Query/Table.
2. Create app shell and `/review`.
3. Add review table filters.
4. Add review detail drawer.
5. Move current review form into drawer.
6. Show placement fields and nearest examples.
7. Add non-reloading mutation flow.

This slice creates the reusable patterns needed for `/files` and `/runs`, and it
immediately improves the current review workflow.

## Reference Documentation

- shadcn/ui docs: https://ui.shadcn.com/docs
- shadcn/ui components: https://ui.shadcn.com/docs/components
- TanStack Table docs: https://tanstack.com/table/latest/docs/framework/react/react-table
- TanStack Table state guide: https://tanstack.com/table/latest/docs/framework/react/guide/table-state
- TanStack Query docs: https://tanstack.com/query
- React PDF Viewer docs: https://react-pdf-viewer.dev/docs
