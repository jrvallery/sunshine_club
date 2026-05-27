# Dashboard Review Cycle UX Roadmap

Last updated: 2026-05-27

## Executive Summary

The dashboard is now functional enough to run files, inspect run reports, browse
files, and review pipeline output. The next problem is workflow clarity. To run
real training and review cycles, the dashboard must make the relationship
between a review item, the run that produced it, and the run configuration
obvious.

Right now, a reviewer can see that a file needs review, but not enough context
about why:

- Was this produced by a fast CPU-only run?
- Was OCR fallback disabled?
- Was LLM tag inspection disabled?
- Were embeddings using Cortex or OpenAI?
- Is this result from the latest run or an older imported run?
- Which run report should be opened to inspect the batch configuration and
  artifact quality?

The dashboard should support this loop:

```text
run pipeline -> review run-specific queue -> correct labels -> compare next run -> measure improvement
```

The first milestone should add run lineage to review items and make the run
report one click away from every review row. After that, the review and file
pages need a UX cleanup so filtering, dense tables, long paths, and text
snippets are easier to scan.

## Current State

Already present:

- Run launcher with provider choices for embeddings, LLM tags, and OCR fallback.
- Per-run report page.
- Review queue with decision workflow.
- File explorer with search, facets, file inspector, preview, and single-file
  run action.
- SQLite review store and FastAPI admin endpoints.
- TanStack Query/Table/Virtual usage in dashboard pages.

Current gaps:

- Review items do not expose run id/run key in the table.
- Review items cannot be filtered by run.
- Review rows do not link to the run report that produced them.
- Review drawer does not explain the run configuration that likely caused the
  issue.
- Review filters are scattered as many raw inputs.
- File explorer table is visually dense; long text/path cells can crowd the
  page.
- Text preview in the Files table is often too cramped to be useful.
- Filtering patterns differ between Review and Files, so users must relearn each
  page.

## Product Goals

### Goal 1: Run-Aware Review

Every review item should make its run lineage clear.

The reviewer should know:

- run id
- run key
- preset
- provider choices:
  - embedding path
  - LLM tag path
  - OCR fallback path
- whether the run was fast/full/custom
- whether OCR fallback and LLM tags were enabled
- whether this review item came from the latest run for that file
- link to the run report

### Goal 2: Efficient Review Cycles

The dashboard should support review by run:

```text
select run -> inspect generated review queue -> resolve/correct -> rerun -> compare
```

Users should be able to filter review items by:

- run id / run key
- preset
- provider configuration
- route status
- review reason
- OCR quality
- primary tag
- content class
- warning type
- placement status
- review state

### Goal 3: Cleaner Dashboard UX

The dashboard should feel like an operational tool:

- consistent filters across Review and Files
- compact, readable tables
- no text overlap
- no giant raw paths in default table columns
- long text shown in inspector/drawer, not crammed into rows
- clear page hierarchy: summary, filters, table, inspector
- one-click navigation between files, review items, and run reports

## Non-Goals

- Do not change source files.
- Do not replace the review decision workflow.
- Do not redesign the pipeline itself in this milestone.
- Do not require a new database system.
- Do not make the Files table a text reading surface; full text belongs in the
  inspector.

## Milestone 1: Run Lineage For Review Items

This is the highest-priority milestone.

### Product Behavior

The Review page should show a run column with a clickable run label:

```text
Run
qa_samples_fast #17
```

Clicking the run label opens:

```text
/runs/{run_id}/report
```

The review table should also show a compact run configuration indicator:

```text
Emb: Cortex | OCR: OpenAI | LLM: Cortex
```

or:

```text
Fast run | OCR fallback off | LLM off
```

This context matters because a poor OCR result from a fast run means something
different than a poor OCR result from a full run with fallback enabled.

### Backend Requirements

Add run lineage to imported review items.

Current import flow should persist:

- `run_id`
- `run_key`
- `preset_key`
- `embedding_provider`
- `llm_tag_provider`
- `ocr_fallback_provider`
- `enable_llm_tags`

Recommended schema changes:

```sql
alter table review_items add column run_id integer;
alter table review_items add column run_key text;
alter table review_items add column run_preset_key text;
alter table review_items add column embedding_provider text;
alter table review_items add column llm_tag_provider text;
alter table review_items add column ocr_fallback_provider text;
alter table review_items add column enable_llm_tags integer;
```

Alternative: store only `run_id` and join to `pipeline_runs` for live metadata.
Recommended approach: store `run_id` plus denormalized snapshot fields. The
snapshot protects audit history if run metadata later changes.

Update:

- `ReviewStore.import_langgraph_output(..., run_id=...)`
- review item insert/update
- review item list/detail serializers
- review export CSV
- review filters

Add API query params:

```text
GET /admin/review/items?run_id=17
GET /admin/review/items?run_preset_key=qa_samples_fast
GET /admin/review/items?embedding_provider=cortex
GET /admin/review/items?llm_tag_provider=openai
GET /admin/review/items?ocr_fallback_provider=openai
```

### Frontend Requirements

Review table columns:

- File
- Run
- Run config
- Reason
- Class
- Primary tag
- Quality
- Warnings
- Review status
- Updated

The Run cell should be a link:

```tsx
<Link href={`/runs/${item.run_id}/report`}>{item.run_key}</Link>
```

Review drawer should show a Run Context section:

- run key
- preset
- provider choices
- command summary
- link to run report
- link to file result in run report, if supported later

### Success Criteria

- Every review item generated from a run has `run_id`.
- Review table shows run context.
- Clicking a run opens the run report.
- Review can be filtered by run id.
- Review export includes run id/run key/provider choices.
- Tests prove import with `run_id` stores lineage.

## Milestone 2: Review Page UX Overhaul

### Problem

The Review page currently has many raw filter inputs in a single horizontal bar.
This is hard to scan and makes the page feel chaotic.

### Target Layout

```text
Header
  Review counts
  Active run filter, if any

Toolbar
  Search
  Saved queue selector
  Clear filters

Main
  Left: Facets / queues
  Center: Review table
  Right: Selected review inspector
```

### Saved Review Queues

Add predefined queues:

- Current run review queue
- OCR poor/empty/gibberish
- Fast-run OCR failures
- LLM tag disagreements
- Low confidence tags
- Placement/date review
- Privacy-sensitive
- Route candidate audit sample
- Technical defer
- Failed extraction

### Filter UX

Replace raw text inputs with:

- search box
- clickable facet counts
- tag pickers
- status segmented controls
- active filter chips
- URL-backed filter state

The user should not need to know exact internal strings like
`review_ocr_quality` to filter correctly.

### Review Inspector

The inspector should group information by decision-making context:

1. Source file
2. Run context
3. Extracted text/OCR
4. Proposed classification and tags
5. Evidence
6. Placement/privacy
7. Review decision form
8. Raw data, collapsed

### Success Criteria

- Filters are URL-shareable.
- Active filters are visible as chips.
- Facets show counts.
- Review by run is one click from a run report.
- Review drawer shows run context and evidence before the decision form.

## Milestone 3: Run Report To Review Workflow

### Product Behavior

The run report should not only summarize a run. It should launch the review work
for that run.

Add to run report:

- Review Queue tab shows generated review items linked to dashboard decisions.
- Button: `Review This Run`
- Button: `Open OCR Failures`
- Button: `Open Tag Disagreements`
- Button: `Open Placement Issues`

Each button navigates to `/review` with URL filters:

```text
/review?run_id=17&review_reason=ocr_quality
```

### Success Criteria

- From a run report, a user can open only that run's review queue.
- Review page displays the active run filter clearly.
- Review decisions made from that queue still update golden labels.

## Milestone 4: File Explorer UX Cleanup

### Current Issue

The File Explorer has useful features but the table is still too text-heavy.
Long OCR snippets and paths can crowd cells. The text column is especially
problematic because it is not a good place to read extracted text.

### Changes

Remove or collapse default text preview from the Files table.

Recommended default columns:

- File
- Type
- Current result
- Review
- Run
- Updated

Move text preview into the inspector only:

- show a small `Text available` / `No text` indicator in the table
- show full extracted text in inspector
- optionally show a hover tooltip with the first 120 characters

Path handling:

- table shows compact path only
- full path visible in inspector
- copy path button remains in inspector

Visual cleanup:

- fixed table row height
- no cell text overlap
- truncate long values with tooltip/title
- status badges for route/quality/review
- avoid nested cards inside cards

### Success Criteria

- Files table rows have stable height.
- No text overlaps in the text/path columns.
- Full text remains accessible in inspector.
- File table is usable on laptop-width screens.

## Milestone 5: Shared Dashboard UI System

### Problem

Review and Files are solving similar UI problems with separate patterns.

### Shared Components

Create reusable components:

- `DashboardSearchToolbar`
- `FacetPanel`
- `ActiveFilterChips`
- `ResultTableShell`
- `InspectorPanel`
- `RunContextBadge`
- `ProviderConfigBadge`
- `PathCell`
- `QualityBadge`

### Benefits

- Review and Files behave consistently.
- Less duplicated filter logic.
- Faster future UX iteration.
- Easier to keep text/path display clean.

### Success Criteria

- Review and Files use shared facet/filter components.
- Run context badge is reused in Review, Files, and Run Report.
- Long path/text rendering is consistent.

## Milestone 6: Training Cycle Dashboard

Once run-aware review is stable, add a page or run-report section that tracks
training/review cycle progress.

### Metrics

Show by run:

- files processed
- review required count
- review rate
- OCR failure rate
- tag disagreement count
- accepted count
- corrected count
- golden labels created
- primary tag accuracy against golden labels
- secondary tag precision/recall
- run-to-run changes

### Workflow

```text
Run A -> review queue -> corrections/golden labels -> rebuild semantic index -> Run B -> compare
```

### Success Criteria

- User can see whether a pipeline change improved review rate and accuracy.
- User can identify which run configuration produced better results.
- Training cycle progress is visible without terminal commands.

## Data Model Additions

### Review Item Run Lineage

Add fields to review items:

| Field | Purpose |
|---|---|
| `run_id` | Canonical link to producing run. |
| `run_key` | Human-readable run label. |
| `run_preset_key` | Fast/full/custom context. |
| `embedding_provider` | Cortex/OpenAI/local context. |
| `llm_tag_provider` | LLM inspection context. |
| `ocr_fallback_provider` | OCR escalation context. |
| `enable_llm_tags` | Whether LLM tag inspection was enabled. |

### Optional File Latest Run Context

The file index already has/latest run concepts. Make sure file rows and
inspection payloads expose:

- latest run id
- latest run key
- latest provider choices
- link to latest run report

## API Additions

### Review Items

Extend:

```text
GET /admin/review/items
GET /admin/review/items/{item_id}
GET /admin/review/export
```

Add filters:

```text
run_id
run_preset_key
embedding_provider
llm_tag_provider
ocr_fallback_provider
enable_llm_tags
```

### Review Facets

Add:

```text
GET /admin/review/facets
```

Facet groups:

- run
- preset
- provider configuration
- review reason
- route status
- primary tag
- content class
- quality
- warning
- placement status
- review status

### Run Report

Extend:

```text
GET /admin/runs/{run_id}/report
```

Add:

- review item ids generated from that run
- review status distribution for that run
- direct dashboard links for review queues

## Implementation Order

### Phase 1: Run Lineage

1. Add review item run lineage columns.
2. Populate lineage during run result import.
3. Add run filters to review API.
4. Add run columns and run report links to Review table.
5. Add Run Context section to Review drawer.
6. Add tests.

### Phase 2: Review UX

1. Replace raw filter bar with search toolbar + facet panel.
2. Add review facets endpoint.
3. Add saved review queues.
4. Add URL-backed filter state.
5. Reorder table columns around review work.

### Phase 3: Run Report Review Links

1. Add `Review This Run` actions.
2. Add per-run review status summary.
3. Link run report tabs to filtered Review page.

### Phase 4: File Explorer Cleanup

1. Remove/collapse text preview column.
2. Add run/latest result column.
3. Stabilize row height and truncation.
4. Move text reading fully to inspector.

### Phase 5: Shared Components

1. Extract shared facet/filter/table/inspector components.
2. Migrate Review first.
3. Migrate Files second.

### Phase 6: Training Cycle Metrics

1. Add cycle metrics to run report.
2. Add run-to-run correction/accuracy summaries.
3. Add rebuild semantic index action after review corrections.

## Acceptance Criteria

This dashboard iteration is successful when:

- Review items show the producing run.
- Review items can be filtered by run id.
- Run id/run key in Review is clickable and opens the run report.
- Review drawer explains run configuration.
- A user can tell whether poor output came from a fast/no-fallback run or a full
  LLM/OCR-enabled run.
- Review filters are organized and not scattered.
- File Explorer no longer crams unreadable OCR text into table cells.
- Long paths/text do not visually overlap.
- Run reports link directly into run-specific review queues.
- The dashboard supports the training loop without terminal-only inspection.

## Recommended First Implementation Ticket

Implement Milestone 1 only:

```text
Run lineage for review items + Review table run links + run_id filter
```

This gives the biggest immediate workflow improvement and creates the data
foundation for the later UX cleanup.
