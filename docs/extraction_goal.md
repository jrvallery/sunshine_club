# Extraction Planning Goal

## Goal

Create an extraction planning layer that turns each corrected content-class
decision into a concrete, auditable extraction strategy.

This layer does not extract content yet. It decides how extraction should happen.

Input:

- `/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/corrected-content-classes.jsonl`

Outputs:

- `extraction-plan.jsonl`
- `extraction-plan-summary.json`

## Why This Exists

Different file types need different extraction behavior.

A scanned scrapbook, searchable PDF, spreadsheet, and photo should not go
through the same pipeline. The extraction planner prevents data loss by choosing
the right path before running OCR or parsers.

## Core User Promise

Every file gets one of:

- a concrete extraction plan
- a technical-defer reason
- an explicit exclusion reason

No file silently disappears.

## File Categories And Plans

### Scanned Document

Includes:

- scanned PDFs
- photographed documents
- scrapbook PDFs
- newspaper/article scans
- forms
- guest lists
- minutes
- receipts
- administrative scans

Plan:

- `strategy = ocr_page_level`
- `ocr_required = true`
- `page_level = true`
- `preserve_layout = true`
- `preserve_page_images = true`
- `search_enabled = true`
- `chat_enabled = true after quality gate`

Subtypes, where inferred:

- `scrapbook`
- `newspaper_article`
- `scanned_or_photographed_document`
- `unknown_scanned_document`

Subtype affects downstream extraction hints, not whether OCR runs.

### Born-Digital Document

Includes:

- searchable PDFs
- Word docs
- text files
- Markdown
- HTML

Plan:

- `strategy = text_extraction`
- `ocr_required = false`
- `ocr_fallback_if_empty = true`
- `page_level = depends_on_format`
- `preserve_layout = optional`
- `search_enabled = true`
- `chat_enabled = true after quality gate`

### Image / Photo

Includes:

- event photos
- historical photos
- member photos
- generic readable images

Plan:

- `strategy = photo_metadata`
- `ocr_required = false`
- `extract_exif = true`
- `extract_dimensions = true`
- `use_path_context = true`
- `search_enabled = metadata_only_initially`
- `chat_enabled = false initially`

If scan-like evidence appears later, image can be escalated to scanned-document
extraction.

### Spreadsheet

Includes:

- `.xlsx`
- `.xls`
- `.csv`
- `.tsv`
- reviewed `.xlsm`

Plan:

- `strategy = spreadsheet_table_extraction`
- `preserve_sheets = true`
- `preserve_rows = true`
- `preserve_columns = true`
- `detect_dates = true`
- `search_enabled = true`
- `chat_enabled = limited after quality gate`

### Deferred Technical

Includes:

- Publisher `.pub`
- shortcuts
- archives
- video
- databases
- photo-edit sidecars
- malformed/conflict files

Plan:

- `strategy = deferred_technical`
- `extract_now = false`
- `search_enabled = false`
- `chat_enabled = false`
- `requires_followup = true`
- `defer_reason = specific reason`

Example defer reasons:

- `publisher_conversion_required`
- `shortcut_resolution_required`
- `archive_unpack_required`
- `video_metadata_required`
- `database_export_required`
- `sidecar_resolution_required`

## Extraction Plan Record

Each row in `extraction-plan.jsonl` should include:

```json
{
  "source_path": "...",
  "relative_path": "...",
  "final_class": "scanned_document",
  "final_status": "accepted",
  "document_subtype": "scrapbook",
  "strategy": "ocr_page_level",
  "ocr_required": true,
  "ocr_fallback_if_empty": false,
  "page_level": true,
  "preserve_layout": true,
  "preserve_page_images": true,
  "extract_metadata": true,
  "search_enabled": true,
  "chat_enabled": false,
  "quality_gate_required": true,
  "defer_reason": null,
  "planning_reasons": [
    "final_class=scanned_document",
    "scrapbook note detected"
  ]
}
```

## Planning Rules

Rules should be deterministic and explainable.

Examples:

- `final_class=scanned_document` -> `ocr_page_level`
- notes contain `scrapbook` -> `document_subtype=scrapbook`
- notes contain `newspaper` or `article` -> `document_subtype=newspaper_article`
- `final_class=image` -> `photo_metadata`
- `final_status=deferred_technical` -> `deferred_technical`
- `final_class=spreadsheet` -> `spreadsheet_table_extraction`

## Success Criteria

### Functional

- Reads `corrected-content-classes.jsonl`.
- Emits exactly one `extraction-plan.jsonl` row per corrected row.
- Emits `extraction-plan-summary.json`.
- Every row has a valid strategy.
- Every deferred file has a specific `defer_reason`.
- Every accepted file has `quality_gate_required = true`.
- No source file is moved, modified, or deleted.

### Coverage

- All `32,467` corrected rows receive a plan.
- `scanned_document` rows map to OCR page-level extraction.
- `document` rows map to text extraction with OCR fallback.
- `image` rows map to photo metadata extraction.
- `spreadsheet` rows map to spreadsheet/table extraction.
- deferred technical rows map to deferred plans with follow-up reasons.

### Safety

- Deferred technical files are excluded from normal search/chat.
- Images are metadata-only initially and excluded from chat until richer
  extraction exists.
- Scanned documents preserve page images/layout.
- Scrapbooks and newspaper articles are not flattened into plain text only.
- Plans are auditable by `planning_reasons`.

### Quality

- Summary includes counts by:
  - final class
  - final status
  - strategy
  - document subtype
  - defer reason
  - search enabled
  - chat enabled
- Tests cover each major file class.
- Tests cover deferred technical cases.
- Tests prove one input row produces one plan row.
- Tests prove invalid or unknown class fails loudly.

## Acceptance Gate

The milestone is complete when:

- `extraction-plan.jsonl` row count equals
  `corrected-content-classes.jsonl` row count.
- `pytest` passes.
- dashboard build passes.
- summary has zero unplanned files.

## Expected Next Step

Implement the first extraction executor node:

- `ocr_page_level` for `scanned_document`

This is the highest-value extraction path because most of the corpus is scanned
material.

## Current Planning Run

Latest generated artifacts:

- `/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/extraction-plan.jsonl`
- `/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/extraction-plan-summary.json`

Acceptance gate:

- corrected rows: 32,467
- extraction plan rows: 32,467
- unplanned files: 0

Strategy counts:

- `ocr_page_level`: 26,058
- `photo_metadata`: 6,072
- `text_extraction`: 255
- `spreadsheet_table_extraction`: 1
- `deferred_technical`: 81

Document subtype counts:

- `scrapbook`: 19,315
- `scanned_or_photographed_document`: 5,145
- `newspaper_article`: 447
- `unknown_scanned_document`: 1,151
- `none`: 6,409

Deferred technical reasons:

- `publisher_conversion_required`: 61
- `shortcut_resolution_required`: 14
- `archive_unpack_required`: 2
- `sidecar_resolution_required`: 2
- `database_export_required`: 1
- `video_metadata_required`: 1
