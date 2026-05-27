# File Browser And Search Redesign

Last updated: 2026-05-27

## Executive Summary

The current Files page is useful as a first pass, but it is trying to be too
many things at once: search UI, file explorer, result table, preview surface,
pipeline launcher, and raw metadata inspector. That makes it noisy and brittle.
When search results get wide or contain complex metadata, the table becomes hard
to read and easy to misinterpret.

The next milestone should redesign the Files page into a real file inspection
workspace:

```text
Find files -> narrow with facets -> inspect one file -> preview source/text/result -> send to run or review
```

The goal is not just prettier search. The goal is to make file discovery and
inspection reliable enough that we can debug classification, OCR, embeddings,
and tagging without dropping back to terminal commands.

## Problem Statement

Current issues:

- The table exposes too much pipeline metadata directly.
- Search results can print strangely because file paths, snippets, tags, and
  JSON-derived fields compete for horizontal space.
- Search is one global text box plus several raw text filters. That does not
  teach the user what filters exist or how many results each filter would
  produce.
- The selected-file drawer is useful, but it does not yet feel like the primary
  inspection workspace.
- There is no clear distinction between:
  - file identity
  - source metadata
  - latest pipeline result
  - review state
  - extracted text/OCR state
  - run actions
- Search currently depends on imported pipeline results. It should also support
  original inventory-level browsing when a file has not been run yet.

## Product Goals

### Goal 1: Make File Search Trustworthy

Users should be able to find a file by:

- filename
- source path
- relative path
- extension
- source collection
- content class
- primary tag
- secondary tag
- OCR/extracted text
- route status
- review status
- warning type
- placement status
- run id or latest run

Search results should always be readable. No raw nested JSON should appear in
the table unless the user opens a raw-data panel.

### Goal 2: Make The Files Page A File Explorer

The page should feel like a searchable archive browser, not just a database
table.

Required explorer capabilities:

- left-side filter/facet panel
- main result list/table
- selected-file detail pane
- source preview
- extracted text/OCR preview
- latest result summary
- review state and actions
- single-file pipeline run action
- copy/open source path affordances

### Goal 3: Support Pipeline Debugging

For any selected file, the dashboard should answer:

- What file is this?
- Where did it come from?
- What did the classifier say?
- What text did extraction/OCR produce?
- What primary and secondary tags were assigned?
- What evidence drove the tags?
- What warnings were generated?
- What destination path would be proposed?
- Has a human reviewed it?
- Has it been used as a golden label?
- What run produced the current result?

## Non-Goals

- Do not replace the Review page. File search is for discovery and inspection;
  Review is for explicit correction workflow.
- Do not build a full document management system.
- Do not move, rename, or mutate source files from the browser.
- Do not require every source file to have a pipeline result before it can be
  found.
- Do not expose all raw JSON fields in the default table.

## Proposed UX

### Page Layout

```text
Header
  Search box
  Saved filter selector
  Result count

Main workspace
  Left: Facets
  Center: Results
  Right: Selected file inspector
```

### Search Bar

The top search box should be a broad text search across filename, path, and
extracted text. It should be debounced and should never crash or block typing.

Recommended behavior:

- 300 ms debounce
- empty search loads recent/indexed files
- minimum 2 characters before text-snippet search, to avoid expensive broad
  scans
- display active query as a removable chip
- support quoted exact path fragments later

### Facet Panel

Facets should be clickable counts, not raw text inputs.

Initial facets:

| Facet | Source |
|---|---|
| Extension | file index |
| Source collection | file index |
| Content class | latest result |
| Primary tag | latest result |
| Secondary tag | latest result |
| Route status | latest result |
| Review status | review item |
| OCR quality | latest result/OCR document |
| Warning | latest result warnings |
| Placement status | latest result |
| Latest run | pipeline run id/run key |

Each facet option should show a count for the current query.

Example:

```text
Primary tag
  meeting_records (184)
  annual_spring_tea (91)
  scrapbooks (74)
```

### Results Table

Default columns should be stable and readable:

| Column | Purpose |
|---|---|
| File | filename plus compact path |
| Type | extension and content class |
| Current result | primary tag, route status, quality |
| Text | short extraction/OCR snippet |
| Review | review status or decision |
| Updated | latest result/import timestamp |

Avoid default columns for long destination paths, full warnings, full metadata,
or raw JSON. Those belong in the selected-file inspector.

Table behavior:

- virtualized rows
- fixed column widths
- column visibility menu
- sort by updated time, filename, tag, quality
- row click selects file
- command-click/open preview where appropriate

### Selected File Inspector

The selected-file panel should become the primary inspection surface.

Sections:

1. Identity
   - filename
   - source path
   - relative path
   - extension
   - mime type
   - size
   - source collection

2. Preview
   - PDF/image/browser preview when supported
   - open original in new tab
   - unsupported-file metadata if preview is not available

3. Extracted Text
   - extracted text snippet
   - full extracted text endpoint
   - OCR quality
   - OCR confidence
   - OCR fallback provider
   - text validation status

4. Latest Pipeline Result
   - content class
   - extraction strategy
   - extraction status
   - primary tag
   - secondary tags
   - confidence
   - evidence
   - competing tags
   - semantic examples
   - placement destination
   - warnings

5. Review State
   - whether it is in review
   - review reason
   - reviewer
   - decision
   - corrected class/tag/placement/privacy
   - golden-label status

6. Actions
   - add to review
   - run single file
   - open latest run report
   - export/copy selected metadata

7. Raw Data
   - collapsed by default
   - latest result JSON
   - file record JSON

## Backend Architecture

### Current Store

The current `ReviewStore` already has:

- file index rows
- latest pipeline result JSON
- review item rows
- extracted text snippets
- run records

The redesign should extend this rather than introduce another store.

### New API Endpoints

#### `GET /admin/files/search`

Purpose: return paginated file result summaries.

Parameters:

- `q`
- `limit`
- `cursor`
- `sort`
- `extension`
- `source_collection`
- `content_class`
- `primary_tag`
- `secondary_tag`
- `route_status`
- `review_status`
- `ocr_quality`
- `warning_type`
- `placement_status`
- `run_id`

Response:

```json
{
  "items": [],
  "next_cursor": null,
  "total_estimate": 1234,
  "query": {}
}
```

The item shape should be a view model, not raw DB rows:

```json
{
  "id": 123,
  "filename": "1992-1993.pdf",
  "compact_path": "Minutes Transcription/.../1992-1993.pdf",
  "source_path": "/mnt/sunshine/...",
  "extension": ".pdf",
  "source_collection": "archive_2026_05_25",
  "content_class": "scanned_document",
  "primary_tag": "meeting_records",
  "secondary_tags": ["membership"],
  "route_status": "route_candidate",
  "quality": "ok",
  "review_status": null,
  "placement_status": "resolved",
  "text_snippet": "Membership ...",
  "latest_run_id": 17,
  "updated_at": "2026-05-27 07:00:00"
}
```

#### `GET /admin/files/facets`

Purpose: return counts for filter UI.

Parameters should mirror `/admin/files/search`.

Response:

```json
{
  "extension": {".pdf": 221, ".jpg": 145},
  "primary_tag": {"meeting_records": 184},
  "route_status": {"route_candidate": 290}
}
```

#### `GET /admin/files/{file_id}/inspection`

Purpose: return the complete selected-file inspection payload.

Response:

```json
{
  "file": {},
  "latest_result": {},
  "review_item": {},
  "golden_label": {},
  "ocr": {},
  "text": {},
  "runs": [],
  "actions": {}
}
```

This should be the only endpoint the right inspector needs after row selection.

### Database Considerations

SQLite is still acceptable for this milestone. Add indexes before adding
another search system.

Recommended indexes:

- `files(filename)`
- `files(extension)`
- `files(source_collection)`
- `pipeline_results(source_path)`
- `pipeline_results(top_tag_candidate)`
- `pipeline_results(final_class)`
- `pipeline_results(route_status)`
- `pipeline_results(quality)`
- expression indexes for common JSON fields only if needed

### Full-Text Search

Add SQLite FTS5 when path/text search becomes slow or inaccurate.

Recommended table:

```sql
file_search_fts(
  filename,
  source_path,
  relative_path,
  extraction_text_snippet,
  content='file_index',
  content_rowid='id'
)
```

Start with filename/path/snippet. Do not index full OCR text until we measure
database size and query time.

## Frontend Architecture

### Components

Recommended component split:

```text
apps/dashboard/app/files/page.tsx
apps/dashboard/components/files/FileSearchBar.tsx
apps/dashboard/components/files/FileFacetPanel.tsx
apps/dashboard/components/files/FileResultsTable.tsx
apps/dashboard/components/files/FileInspector.tsx
apps/dashboard/components/files/FilePreviewPanel.tsx
apps/dashboard/components/files/FileResultSummary.tsx
```

### State Model

Use URL query params as the source of truth for search/filter state:

```text
/files?q=minutes&primary_tag=meeting_records&quality=poor
```

Benefits:

- shareable searches
- browser back/forward works
- reload preserves state
- saved filters can be represented as URLs

Use TanStack Query for API state:

- `["file-search", filters]`
- `["file-facets", filters]`
- `["file-inspection", fileId]`

### Search Interaction

Typing should only update local input immediately. URL/query state should update
after debounce.

Flow:

```text
input state -> debounce -> URL params -> TanStack Query fetch
```

This prevents the table from trying to rebuild on every keystroke.

### Result Rendering Rules

Never render untrusted/unknown values directly in table cells.

Rules:

- arrays render as comma-separated chips or compact text
- objects render only as a short summary, never raw JSON
- paths are compacted in table cells and full in tooltip/detail panel
- text snippets are capped by character count
- warnings are collapsed into count + top warning
- raw JSON is only visible in a collapsed inspector panel

## Implementation Plan

### Step 1: Stabilize Current Files Page

Deliverables:

- fixed-width virtual table columns
- readable compact path rendering
- safe table-cell formatting
- snippet length caps
- no raw nested objects in the result table

Success criteria:

- typing in search does not crash
- table remains readable at laptop width
- no `[object Object]` or huge raw JSON appears in default table cells

### Step 2: Add Search View Models

Deliverables:

- `GET /admin/files/search`
- explicit file search result DTO
- backend tests for result shape
- frontend uses the new endpoint instead of raw file rows

Success criteria:

- every table cell is backed by an intentional field
- changing backend raw result JSON cannot break table rendering
- file search still returns current dashboard results

### Step 3: Add Facets

Deliverables:

- `GET /admin/files/facets`
- left-side facet panel
- clickable facet options
- active filter chips
- URL-backed filters

Success criteria:

- users can narrow results without typing exact internal enum values
- facet counts update based on the current search
- active filters can be removed individually

### Step 4: Build File Inspector Payload

Deliverables:

- `GET /admin/files/{file_id}/inspection`
- right-side inspector uses one endpoint
- preview/text/latest result/review state/actions are grouped

Success criteria:

- selecting a file shows source metadata, extracted text, latest tags, evidence,
  warnings, placement, review state, and run links without opening raw JSON
- raw JSON remains available but collapsed

### Step 5: Add Saved Searches

Deliverables:

- saved searches table or local config file
- save current filters as named search
- initial saved searches:
  - OCR poor or empty
  - route candidates needing precision audit
  - meeting records
  - annual tea materials
  - unknown/failed extraction
  - placement missing date

Success criteria:

- common audit workflows are one click
- saved search URL can be shared or reopened later

### Step 6: Add Optional FTS5

Deliverables:

- FTS table
- rebuild endpoint or import hook
- query planner fallback if FTS table is missing

Success criteria:

- filename/path/snippet search remains responsive on the full corpus
- query behavior is deterministic and covered by tests

## Success Criteria

The milestone is successful when:

- A user can find a known file by filename, path fragment, or OCR text.
- A user can narrow files by tag/class/quality/review status using facets.
- The Files page remains readable on a laptop screen.
- Selecting a file gives enough context to understand how the pipeline handled
  it.
- A user can send a file to review or run it through the pipeline from the
  inspector.
- No raw nested JSON appears in default search results.
- Search/filter state is URL-shareable.
- Backend search results are explicit view models with tests.
- The page remains responsive with at least several thousand indexed files.

## Test Plan

Backend tests:

- search by filename
- search by path
- search by extracted text snippet
- filter by extension
- filter by primary tag
- filter by secondary tag
- filter by route status
- filter by review status
- facet counts respect current filters
- inspection endpoint returns file/result/review/text/run sections

Frontend tests:

- typing search does not crash
- filters update URL params
- active filters can be removed
- selecting a row opens inspector
- inspector loads preview/text/result sections
- raw metadata is collapsed by default

Manual QA:

- search for a known minutes PDF
- search for a scrapbook image
- search for a poor OCR result
- filter to `meeting_records`
- filter to `review_required`
- run a selected file
- add a selected file to review

## Open Questions

- Should saved searches live in SQLite, checked-in config, or browser local
  storage?
- Should full OCR text be indexed immediately, or only snippets until we know
  database size?
- Should unsupported files show a binary/technical inspection panel?
- Should the file explorer show source folder hierarchy as a tree in addition
  to search results?
- How aggressively should file search include historical runs versus only the
  latest result?

## Recommended Next Milestone

Build Steps 1-4 first. Saved searches and FTS can follow after the basic
explorer is stable.

The milestone should end with the Files page becoming the default place to
answer: “What happened to this file, and what should I do with it next?”
