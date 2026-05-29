# Dashboard Rebuild Design

Last updated: 2026-05-28.

## Goal

Rebuild the Sunshine Club dashboard as a coherent Postgres-backed review and pipeline console while preserving every workflow that already exists.

The backend is now healthy enough to treat Postgres as the source of truth. The frontend should stop feeling like separate test pages stitched together. Every page should have a clear job, a consistent layout, predictable drill-down behavior, and one-click navigation between runs, files, reviews, labels, and search results.

Primary product loop:

```text
start run -> monitor run report -> inspect flagged files -> record review decisions
-> create golden labels -> rebuild/search embeddings -> rerun -> compare improvement
```

## Non-Negotiables

- Do not remove existing functionality.
- Default all operational views to Postgres. Do not expose SQLite as a normal user option.
- Every table row that represents a file, review item, run, label, segment, or search result must be clickable.
- Every detail page must link back to its source run and source file when those fields exist.
- Every run-generated review item must be discoverable both from the run report and from the global review queue.
- No source files are modified by the dashboard. Source files are read-only.
- No hosted third-party APIs should be assumed by the UI. Model usage should still display external cost fields when a run used an external provider.
- Preserve dark mode and restrained Sunshine yellow accent styling.

## Current Pages To Preserve

| Current route | Keep? | Future role |
|---|---:|---|
| `/review` | Yes | Global review queue with filters, bulk triage, and run-aware review rows. |
| `/review/[reviewId]` | Yes | Focused review workspace for one review item. |
| `/files` | Yes | Corpus browser and search page. |
| `/files/[fileId]` | Yes | File detail, preview, text, pipeline history, and actions. |
| `/runs` | Yes | Run launcher and run history. |
| `/runs/[runId]/report` | Yes | Durable run report for active and completed runs. |
| `/golden-labels` | Yes | Golden label management and training-set coverage. |
| `/pipeline-eval` | Yes | Pipeline evaluation and provider benchmark workspace. |
| `/reports` | Rename/reframe | Use as `Search` or move semantic search to `/search`; avoid a vague Reports page. |
| `/settings` | Yes | System health, provider status, Postgres/Qdrant/Cortex/Docling status. |

## Recommended Navigation

Sidebar order:

1. `Review`
2. `Files`
3. `Runs`
4. `Search`
5. `Golden Labels`
6. `Evaluations`
7. `Settings`

Top-level page titles should always include a short subtitle and relevant global stats. Avoid large empty hero sections. This is an operations console.

## Design System

Use the current Next.js app as the base, but rebuild around a smaller set of reusable primitives.

Recommended libraries:

| Need | Recommended tool |
|---|---|
| App framework | Existing Next.js App Router |
| Server state | TanStack Query |
| Tables | TanStack Table |
| Virtual long tables | TanStack Virtual |
| Forms | React Hook Form + Zod |
| Command/search menus | shadcn/ui Command or existing custom combobox |
| Layout/sidebar/tabs/dialogs | shadcn/ui-style components or existing local equivalents |
| Charts | Recharts only where charts add clarity |
| PDF rendering | Browser iframe first; add PDF.js only if page navigation/text overlay is required |

Visual rules:

- Dark theme first.
- Background: near-black charcoal, not pure black.
- Accent: minimal Sunshine yellow for active states, focus rings, selected chips, and primary buttons.
- Avoid nested cards. Use full-width panels and tables.
- Tables need clear row separation, fixed column priorities, and no crammed paragraph text.
- Long paths must use truncation plus tooltip/copy action.
- Text snippets should be limited to 2-4 lines with an expand control.
- Raw JSON belongs in collapsible panels, never in the primary scan path.

## Shared Layout Pattern

Every major list page should use the same structure:

```text
Page header
  title, subtitle, main action
  metric strip

Filter/search band
  saved views
  primary search
  high-value filters
  active filter chips

Main content
  table/list
  right-side inspector or click-through detail route

Footer/status
  last refreshed, result count, pagination/cursor
```

Every detail page should use:

```text
Breadcrumbs
Header with identity and status
Primary actions
Linked context strip
Tabs
  Overview
  Preview/Text
  Pipeline Evidence
  Review/Labels
  Raw/Artifacts
```

## Backend Contract

All dashboard requests should go through the Next proxy under `/api/admin/...`, which forwards to the FastAPI admin API.

### Source Policy

Always call Postgres endpoints with `source=postgres` where the endpoint still accepts a source parameter.

SQLite routes may still exist internally for old tooling, but the new dashboard should not expose a SQLite selector.

### Runs

| UI need | Endpoint |
|---|---|
| List presets | `GET /api/admin/runs/presets` |
| Start run | `POST /api/admin/runs` |
| List runs | `GET /api/admin/runs?source=postgres&limit=...` |
| Run report | `GET /api/admin/system/postgres-runtime/runs/{runKey}/report` |
| Run raw results | `GET /api/admin/runs/by-key/{runKey}/results` |
| Cancel run | `POST /api/admin/runs/by-key/{runKey}/cancel` |
| Import run results | `POST /api/admin/runs/by-key/{runKey}/import-results` |
| Delete run | `DELETE /api/admin/runs/by-key/{runKey}` |

Run table required columns:

- Status
- Run key
- Preset
- Started
- Updated/completed
- Processed/imported results
- Review items/open review items
- Segments
- Chunks/embeddings
- Model calls
- External cost
- Provider summary
- Actions

Run rows must link to `/runs/{runKey}/report`.

### Run Report

The report page must work while a run is active and after it completes.

Report sections:

1. Header
   - run key
   - preset
   - status
   - input root
   - output dir
   - started/updated/completed
   - action buttons: cancel, import results, delete, rerun, copy run key

2. Progress
   - processed vs selected/expected when available
   - imported results
   - review items
   - failures
   - live event freshness
   - show indeterminate progress when total is unknown

3. Model Usage
   - total model calls
   - local calls
   - external calls
   - provider/model breakdown
   - input/output tokens when available
   - runtime when available
   - external cost when available
   - embedding rows must count as model usage

4. Pipeline Counts
   - parser results
   - OCR pages
   - segments
   - chunks
   - embeddings
   - provider attempts
   - provider selections
   - quality checks
   - tag evidence
   - file metadata
   - artifacts
   - processing artifacts

5. Result Distribution
   - content class
   - primary tag
   - route status
   - quality
   - segment type
   - provider attempt status

6. Review Queue For This Run
   - same columns as global review queue
   - every item links to `/review/{reviewId}`
   - include file link and run context

7. Files In This Run
   - each result row links to `/files/{fileId}` if a Postgres file/result id exists
   - include status, tag, class, quality, extracted text snippet

8. Events
   - timeline table
   - default to latest 500 shown
   - clearly show total vs shown if the API is capped

9. Artifacts
   - artifact name, kind, row count, size, exists/missing
   - link to raw artifact where safe

Known counter cleanup required:

- Do not label capped event rows as the total count. Show `500 shown / 781 total` if available.
- Distinguish `files requiring review` from `review item rows`; one file can create multiple review items.
- Distinguish `artifact manifest entries` from `artifact database rows`.
- If selected count and processed count differ, show a warning panel and list missing/unfinished graph runs if available.

### Review

| UI need | Endpoint |
|---|---|
| Summary | `GET /api/admin/review/summary?source=postgres` |
| List review items | `GET /api/admin/review/items?source=postgres&status=...&run_key=...` |
| Review facets | `GET /api/admin/review/facets?source=postgres&...` |
| Review item detail | `GET /api/admin/review/items/{itemId}?source=postgres` |
| Original file | `GET /api/admin/review/items/{itemId}/file?source=postgres` |
| Download file | `GET /api/admin/review/items/{itemId}/download?source=postgres` |
| Record decision | `POST /api/admin/review/items/{itemId}/decision?source=postgres` |
| Golden labels | `GET /api/admin/review/golden-labels?source=postgres` |
| Golden label summary | `GET /api/admin/review/golden-labels/summary?source=postgres` |
| Update golden label | `PATCH /api/admin/review/golden-labels/{labelId}?source=postgres` |
| Delete golden label | `DELETE /api/admin/review/golden-labels/{labelId}?source=postgres` |

Review table columns:

- File
- Run
- Status
- Reason
- Class
- Primary tag
- Secondary tags
- Quality
- Confidence
- Placement
- Provider config
- Updated
- Actions

The run column must be a compact badge linking to `/runs/{runKey}/report`.

Review filters:

- status
- run key
- preset
- route status
- review reason
- primary tag
- secondary tag
- content class
- quality
- placement status
- warning type
- source collection
- provider config
- free-text search

Review detail layout:

```text
Header
  filename, status, reason, quality
  run link, file link
  actions: accept, change, defer, save golden, next

Left pane
  original preview

Right pane tabs
  Extracted Text
  OCR Evidence
  Tag Evidence
  Placement
  Segments
  Raw

Decision footer
  correct class
  correct primary tag
  secondary tags
  OCR quality
  expected review required
  privacy/sensitive flag
  destination path/year
  reviewer/notes
```

Decision workflow:

- `Accept`: records the proposed class/tag/placement as correct.
- `Change`: requires corrected fields.
- `Defer OCR`: marks OCR quality or extraction problem.
- `Defer Technical`: unsupported/corrupt file.
- `Save as golden`: available for accept/change decisions.
- After saving, show next item from the current filtered queue.

### Files

| UI need | Endpoint |
|---|---|
| Search/list files | `GET /api/admin/files/search?source=postgres&...` |
| Facets | `GET /api/admin/files/facets?source=postgres&...` |
| File detail | `GET /api/admin/files/{fileId}?source=postgres` |
| Inspection bundle | `GET /api/admin/files/{fileId}/inspection?source=postgres` |
| Preview original | `GET /api/admin/files/{fileId}/preview?source=postgres` |
| Download original | `GET /api/admin/files/{fileId}/download?source=postgres` |
| Extracted text | `GET /api/admin/files/{fileId}/text?source=postgres` |
| Add to review | `POST /api/admin/files/{fileId}/review?source=postgres` |
| Run single file | `POST /api/admin/files/{fileId}/run?source=postgres` |

File browser table columns:

- File
- Type/extension
- Content class
- Primary tag
- Secondary tags
- Quality
- Route/review status
- Latest run
- Updated
- Text snippet

Do not show full source paths as giant table text. Use `PathCell` style truncation and an inspector panel for full paths.

File detail tabs:

- Overview: path, extension, size, class/tag/quality, run lineage.
- Preview: embedded PDF/image/text where possible.
- Text: extracted text, OCR text, page/chunk snippets.
- Pipeline: latest parser result, quality checks, provider attempts, tag evidence.
- Segments: proposed document segments/page ranges.
- Reviews: review items linked to this file.
- Raw: JSON payloads for debugging.

### Search

The current `/reports` page is really semantic search. Rename navigation label to `Search` and either keep route `/reports` temporarily or migrate to `/search` with redirect.

| UI need | Endpoint |
|---|---|
| Semantic search | `POST /api/admin/search/semantic` |
| Vector status | `GET /api/admin/semantic-index/status` |
| Rebuild Qdrant | `POST /api/admin/vector-index/qdrant/rebuild` |

Search result rows:

- score
- file/path
- run key
- chunk kind
- primary tag
- content class
- segment/page range
- snippet
- actions: open file, open run, add to review

### Golden Labels

Golden label page should use Postgres by default and remove the source toggle.

Required sections:

- Metrics: total labels, primary coverage, secondary coverage, mismatches, indexed labels.
- Filters: primary tag, secondary tag, content class, OCR quality, reviewer, mismatch only, source collection.
- Table: file, correct tag, proposed tag, class, OCR quality, reviewer, updated, run.
- Editor drawer: same correction fields as review decision form.
- Actions: edit, delete, open source file, open originating review, rebuild semantic index.

### Evaluations

Keep `/pipeline-eval`, but make it visually consistent with the rest of the dashboard.

Required areas:

- Golden set evaluation runs.
- Provider benchmark runs.
- Current vs baseline comparison.
- Failure groups.
- Model usage.
- Provider promotion plan.

Rows must link to files, runs, and review items when identifiers exist.

### Settings

Settings should answer: “Is local infrastructure healthy enough to run the pipeline?”

Sections:

- API health.
- Postgres runtime summary.
- Qdrant/vector store status.
- Cortex status.
- Docling/provider registry status.
- Model cache.
- Temporal status, if enabled.
- Environment policy: local-only, hosted APIs allowed/blocked.

## Data Shape Rules For Frontend

Normalize API results into view models before rendering. The UI should never directly render arbitrary objects.

Create frontend adapters:

```text
lib/view-models/run.ts
lib/view-models/review.ts
lib/view-models/file.ts
lib/view-models/golden-label.ts
lib/view-models/search.ts
```

Each adapter should:

- convert missing values to `null` or `"-"` for display
- build stable row ids
- derive display status/tone
- derive links
- trim snippets
- flatten provider/model fields
- preserve raw payload for debug tabs

Stable row key rules:

- Run: `run_key`
- Review item: `id`
- File result: `id` or stable Postgres result id
- Segment: `segment_id || file_id + page_start + page_end + index`
- Artifact: `run_key + path + name + index`
- Event: event id if present, else `run_key + timestamp + index`

Never key React rows only by source path; multiple rows can share one source file.

## Click-Through Map

| From | Click | To |
|---|---|---|
| Run history row | run key/status | `/runs/{runKey}/report` |
| Run report review row | review id/open | `/review/{reviewId}` |
| Run report file row | file/path | `/files/{fileId}` |
| Review queue row | file/title | `/review/{reviewId}` |
| Review detail run badge | run key | `/runs/{runKey}/report` |
| Review detail file badge | file id/path | `/files/{fileId}` |
| File browser row | file/path | `/files/{fileId}` |
| File detail run row | run key | `/runs/{runKey}/report` |
| File detail review row | review id | `/review/{reviewId}` |
| Search result | file/path | `/files/{fileId}` |
| Search result | run key | `/runs/{runKey}/report` |
| Golden label row | source file | `/files/{fileId}` or preview endpoint |
| Golden label row | review item | `/review/{reviewId}` |

## Implementation Milestones

### Milestone 1: Shared Shell And Data Contracts

Goals:

- Define route inventory, shared layout, and adapters.
- Remove SQLite selectors from normal UI.
- Introduce common page header, metric strip, filter band, active filters, table shell, detail tabs, empty/error states.

Success criteria:

- All existing routes still load.
- No page exposes SQLite as a normal source.
- Every table uses stable keys and no raw object rendering.
- Common loading/error/empty states are visually consistent.

### Milestone 2: Runs And Run Report

Goals:

- Make `/runs` the single place to start, cancel, delete, and inspect runs.
- Make `/runs/{runKey}/report` accurate for active and completed runs.
- Display total-vs-shown event counts and clear model usage.

Success criteria:

- Starting a run shows queued/running status within one polling interval.
- Live counts update while the run runs.
- Cancel/delete/import actions work against Postgres run keys.
- Review items for a run are visible on the run report.
- Report counters distinguish files, review rows, segments, chunks, model calls, and artifacts.

### Milestone 3: Review Workspace

Goals:

- Rebuild global review queue and review detail around run-aware review.
- Make decisions fast and auditable.
- Allow corrected labels to become golden labels.

Success criteria:

- Review queue can filter by run key and preset.
- Every review item links to its run report and file detail.
- Decision form can accept/change/defer and save as golden.
- After decision save, the item leaves the open queue or updates status immediately.
- No review item created by a run is hidden from the global queue.

### Milestone 4: File Browser And Detail

Goals:

- Make file search usable for investigation.
- Move dense text/path data into detail views instead of cramming table cells.
- Support single-file reruns and add-to-review.

Success criteria:

- Search does not crash while typing.
- Filters and facets update without resetting unrelated state.
- File detail shows original preview, extracted text, segments, latest run, reviews, and raw payload.
- Single-file run action starts a run and links to its run report.

### Milestone 5: Search, Golden Labels, Evaluations

Goals:

- Make semantic search citation-first.
- Make golden labels clearly editable and tied to source evidence.
- Keep pipeline eval/provider benchmarks available but visually consistent.

Success criteria:

- Semantic search results link to file, run, and review context.
- Golden labels default to Postgres and can be edited/deleted.
- Rebuild semantic/vector index action is visible and status is clear.
- Evaluation failures can be drilled into and linked back to source files.

### Milestone 6: Polish And Regression Tests

Goals:

- Prevent another fractured dashboard.
- Add smoke tests around the core navigation and API assumptions.

Success criteria:

- Playwright smoke test covers: runs list, run report, review list/detail, files list/detail, golden labels.
- Tests assert no console errors on primary pages.
- Tests assert key click-through links exist.
- TypeScript build passes.
- Lint passes.
- Empty Postgres database state renders useful empty states.

## Frontend Test Plan

Minimum tests:

1. `runs.spec.ts`
   - loads run list
   - opens a run report
   - validates report sections exist

2. `review.spec.ts`
   - loads review queue
   - opens review detail
   - validates run/file links exist

3. `files.spec.ts`
   - loads file browser
   - types into search
   - opens file detail
   - validates preview/text tabs do not crash

4. `golden-labels.spec.ts`
   - loads labels
   - filters by primary tag
   - opens editor drawer

5. `navigation.spec.ts`
   - every sidebar link loads without console errors

## Backend Gaps To Flag To Backend Agent

The frontend agent should not silently work around these if they appear:

- Run report currently caps events; the API should expose total count separately from returned rows.
- Some endpoints still accept `source=sqlite`; frontend should use Postgres, but backend should eventually retire or hide SQLite.
- Single-file run from `/admin/files/{fileId}/run` may still use legacy SQLite run creation internally. If this blocks Postgres-only UX, escalate to backend.
- Review facets in Postgres mode currently filter in memory from a capped row list. This is acceptable for now but should move to SQL if queues grow.
- If selected sample count differs from result count, the API should expose missing/unfinished sample diagnostics.

## Definition Of Done

The rebuild is done when a user can:

1. Start a run from `/runs`.
2. Watch live progress and model usage in the run report.
3. Click review-required items from the run report into `/review/{reviewId}`.
4. Inspect original file, extracted text/OCR, tag evidence, placement, and raw debug data.
5. Record a review decision and optionally save it as a golden label.
6. Search files and semantic chunks, then click into file/run/review context.
7. Manage golden labels and rebuild the semantic index.
8. Run evaluations and inspect failures.
9. Do all of this without seeing SQLite controls, raw object rendering, table overlap, duplicate-key warnings, or console crashes.

