# Sunshine Club Corpus Inventory

Last checked: 2026-05-25 against `/mnt/sunshine`.

## Mounted Source Root

The Phase 1 source root is the Atlas VM NAS mount:

- `/mnt/sunshine`

Main areas under that root:

- `Sunshine shared folders/` - Cloud Sync / Google Drive-synced Sunshine folder.
- `From Mac Sunshine Pass 2026-05-25/` - review pass for Emily's `from mac/Sunshine in Progress` folder.
- `Paige Agent Sunshine Files/` - Paige-local memory, vault, work, and temporary artifacts copied out of the agent workspace.
- `google-drive-delta-2026-05-25/` - live Google Drive files missing or mismatched at the same local path.
- `archive-2026-05-25/` - raw source-path archive of local Sunshine-related files from older shares and workspaces.
- `_manifest/` - inventory, comparison, and copy logs.

## Manifested Corpus Shape

The broad local inventory manifest currently contains 31,910 rows, including 31,907 local files planned for copy and 3 external metadata-only rows. The planned local copy volume is about 150.294 GiB.

Source groups:

- `canonical_nas_sunshine_root`: 23,517 rows.
- `mac_import_sunshine_in_progress_and_google_drive_export`: 5,067 rows.
- `microsoft_onedrive_backup_sunshine_root`: 2,019 rows.
- `filename_or_content_match`: 486 rows.
- `paige_context_content_match`: 477 rows.
- `legacy_onedrive_fastfoto`: 298 rows.
- `sunshine_dashboard_workbooks`: 43 rows.
- Slack metadata-only Sunshine handoff files: 2 rows.
- Live Google Drive metadata-only search result: 1 row.

Live Google Drive inventory:

- 19,900 records.
- 19,212 files.
- 688 folders.
- 89.087 GiB listed.
- Same-path/same-size local matches: 19,135 files.
- Missing or size-mismatched local files: 77 files / about 17 MB, copied to `google-drive-delta-2026-05-25/`.

Emily's From Mac pass:

- 5,067 files / 15.763 GiB inventoried.
- 4,916 files already represented in the main Drive inventory by filename and byte size.
- 151 files / 80.10 MB not found in the main Drive inventory and copied for review.
- 619 duplicate filename+size groups inside the From Mac source.

## Dominant File Types

The corpus is image-heavy. The pipeline must not assume most files are born-digital text documents.

Manifest extension counts:

- `jpg`: 21,655 files / about 121.5 GiB.
- `jpeg`: 7,245 files / about 13.0 GiB.
- `tif`: 1,039 files / about 11.8 GiB.
- `md`: 401 files.
- `txt`: 291 files.
- `docx`: 234 files.
- `eml`: 225 files.
- `pdf`: 224 files / about 3.3 GiB.
- `xlsx`: 175 files.
- `png`: 152 files.
- `json`: 59 files.
- `py`: 57 files.
- `csv`: 30 files.
- `pub`: 12 files.
- `pptx`: 9 files.
- Smaller counts include `tsv`, `html`, `msg`, `heic`, `gif`, `xls`, `db`, `avif`, shell/script/config files, and Synology metadata sidecars.

Google Drive MIME types show the same shape:

- `image/jpeg`: 17,483 files.
- `image/tiff`: 806 files.
- Google Drive folders: 688 records.
- `docx`: 187 files.
- `pdf`: 165 files.
- `xlsx`: 123 files.
- `image/png`: 120 files.
- `text/markdown`: 97 files.
- `text/plain`: 87 files.
- Google-native docs: 36 files.
- ZIP/octet/code/email and presentation formats appear in smaller counts.

## Pipeline Implications

Content classes should be assigned during inventory, before extraction, then revised when extraction reveals better evidence:

- `image`: photo-first files such as `jpg`, `jpeg`, `png`, `heic`, `avif`, and `gif`.
- `scanned_document`: image/PDF/TIFF files likely to contain documents, receipts, scrapbook pages, minutes, labels, or scans.
- `document`: PDF, Word, Markdown, plain text, HTML, and similar text-bearing files.
- `spreadsheet`: `xlsx`, `xls`, `csv`, and `tsv`.
- `presentation`: `pptx` and related deck formats.
- `email`: `eml` and `msg`.
- `google_native_export`: Google Docs/Sheets/Slides exported from Drive.
- `manifest`: inventory, copy log, comparison, and pipeline-generated metadata files.
- `code_or_workspace_artifact`: Python, TypeScript, config, package metadata, caches, and agent workspace files.
- `binary_or_unknown`: everything else until reviewed or classified.

Extraction routing should follow content class:

- Born-digital documents go through Docling first.
- PDFs or image files that look scanned go through OCR as a primary extraction path.
- TIFFs need explicit OCR/image handling; many are likely historical scans.
- Spreadsheets should preserve sheets, rows, date-like columns, and workbook metadata.
- Emails should preserve headers, sender/recipient/date, attachments, and body text.
- Photos should prioritize EXIF/captured date, folder context, event inference, face/name captions when available, and deterministic photo placement. They should not all be forced through text-centric semantic tagging.
- Manifest and workspace artifacts are ingestable for audit/provenance, but should be excluded from normal user search/chat unless explicitly promoted.

OCR/document extraction should produce a normalized artifact, not just plain text:

- page-level text
- paragraphs or blocks
- tables if detected
- page numbers
- coordinates and confidence when available
- preprocessing and quality warnings

If OCR upgrades an `image` into a `scanned_document`, that content-class change should be stored as part of extraction provenance.

## Safety Rules

- Do not delete duplicate-looking files from the NAS pass without review.
- Treat filename+size duplicate detection as conservative evidence, not final truth.
- Preserve original source path and source collection for every row.
- Keep the NAS copy as archive during MVP even after Drive import.
