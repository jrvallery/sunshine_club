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

## Inventory Quality Gate

The current inventory command is:

```bash
python -m sunshine_connectors.inventory /mnt/sunshine \
  --output /mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/inventory.jsonl \
  --summary /mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/summary.json \
  --skipped-audit /mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/skipped-files.jsonl \
  --probe-manifest /mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/probe-manifest.jsonl \
  --inventory-run-id sunshine-club-inventory-2026-05-25
```

The generated JSONL file is the reusable staged-file inventory. Each emitted row
includes:

- source type
- source collection
- absolute source path
- relative source path in `raw_metadata.relative_path`
- inventory run ID in `raw_metadata.inventory_run_id`
- filename
- extension
- MIME type
- size
- source mtime
- optional checksum status or value
- initial content class, confidence, classifier name/version, rule ID, and reasons
- content-class stage, currently `initial_inventory`
- extraction probe and review-required flags
- risk flags such as `low_confidence_content_class`, `needs_extraction_probe`, and `binary_or_unknown`

The skipped-file audit JSONL is the reviewable record of files intentionally
omitted from the inventory. Each skipped row includes source path, relative path,
name, extension, MIME type, size, mtime, skip reason, audit disposition, and the
same inventory run ID. Current skips are restricted to explicit system,
temporary, cache, lock, and sidecar patterns.

The probe manifest JSONL is the input queue for the next extraction confidence
pass. It contains emitted files that should not be trusted from path/extension
alone:

- low-confidence content-class assignments
- PDFs/images with explicit extraction probe reasons
- `binary_or_unknown` files

Probe rows include source provenance, initial content class, confidence, reasons,
risk flags, and a safety policy stating that source mutation is not allowed and
failed or empty probes require review.

The summary JSON is the quality report. It includes:

- scanned file count
- emitted file count
- skipped file count
- counts by source collection
- counts by content class
- counts by extension
- counts by skipped reason
- low-confidence assignment count and samples
- `binary_or_unknown` count and samples
- files needing extraction probes and samples
- probe manifest count and samples

### Content-Class Transition Contract

Extraction probes must not overwrite the inventory decision in place. They should
emit a content-class transition record with:

- inventory run ID
- source path
- before class
- after class
- transition reason
- extractor name and version
- extraction quality
- warnings
- review-required flag

This preserves the original heuristic decision and makes every later correction
auditable.

The extraction probe run should also emit a probe audit summary with:

- inventory run ID and probe run ID
- total probe candidates
- unchanged classifications
- changed classifications
- failed extractions
- empty or poor extractions
- still-unknown files
- review-required files
- skipped files by reason
- transition counts such as `image->scanned_document`

Current probe command:

```bash
python -m sunshine_extraction.probe \
  /mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/probe-manifest.jsonl \
  --results /mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/probe-results.jsonl \
  --summary /mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/probe-summary.json \
  --probe-run-id sunshine-club-probe-2026-05-25
```

The probe pass is read-only against source files. It classifies evidence as a
transition record and leaves the inventory rows unchanged.

### Current Probe Run

Latest lightweight probe run:

- probe manifest JSONL: `/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/probe-manifest.jsonl`
- probe results JSONL: `/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/probe-results.jsonl`
- probe summary JSON: `/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/probe-summary.json`
- probe run ID: `sunshine-club-probe-2026-05-25`
- manifest rows: 32,467
- result rows: 32,467
- missing results: 0
- extra results: 0

Probe outcomes:

- probed: 31,512
- failed extraction probes: 955
- unchanged content classes: 32,201
- changed content classes: 266
- empty or poor extraction probes: 1,086
- still unknown: 81
- review required: 146

Content-class transitions:

- `scanned_document->scanned_document`: 25,894
- `image->image`: 6,072
- `image->scanned_document`: 93
- `scanned_document->document`: 131
- `document->scanned_document`: 41
- `document->document`: 154
- `binary_or_unknown->binary_or_unknown`: 81
- `binary_or_unknown->spreadsheet`: 1

Top review reasons:

- `pdf_too_large_for_lightweight_probe`: 45
- `publisher_file_review`: 44
- `extensionless_file_review`: 16
- `unsupported_binary_review`: 16
- `pdf_probe_failed`: 15
- `pdf_sparse_text`: 4
- `shortcut_review`: 2
- `archive_review`: 2
- `video_review`: 1
- `macro_enabled_spreadsheet_review`: 1

### Current Run

Latest full no-checksum run:

- inventory JSONL: `/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/inventory.jsonl`
- summary JSON: `/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/summary.json`
- skipped-file audit JSONL: not generated in the last recorded run
- probe manifest JSONL: not generated in the last recorded run
- scanned files: 32,111
- emitted files: 31,513
- skipped files: 598

Content-class counts:

- `scanned_document`: 26,400
- `image`: 3,386
- `document`: 1,275
- `spreadsheet`: 234
- `code_or_workspace_artifact`: 112
- `binary_or_unknown`: 55
- `manifest`: 35
- `presentation`: 9
- `email`: 7

Skipped reasons:

- `skip_directory:tmp`: 586
- `skip_directory:@eadir`: 6
- `skip_file:.ds_store`: 4
- `skip_directory:#recycle`: 1
- `skip_suffix:.tmp`: 1

Quality flags:

- low-confidence content-class assignments: 28,504
- `binary_or_unknown`: 55
- needs extraction probe: 3,191

The large low-confidence count is expected for this first gate because many
image/PDF cases require extraction evidence before they can be trusted as
photos, scans, or born-digital documents.

### Skip Policy

The inventory omits known system junk and operational noise:

- `.DS_Store`
- `desktop.ini`
- `Thumbs.db` / `ehthumbs.db`
- `#recycle/`
- Synology `@eaDir/`
- macOS metadata directories such as `.Trashes`, `.Spotlight-V100`, `.fseventsd`, and `.TemporaryItems`
- VCS/cache/build directories such as `.git`, `.hg`, `.svn`, `node_modules`, `.next`, `__pycache__`, and test/lint caches
- temporary directories named `tmp` or `temp`
- AppleDouble files beginning with `._`
- Office lock files beginning with `~$` or `.~lock.`
- temporary/download/cache suffixes such as `.tmp`, `.temp`, `.swp`, `.swo`, `.part`, `.download`, `.crdownload`, `.lock`, and `.pyc`

The inventory does not blindly omit every binary file. Unknown or unsupported
files remain visible as `binary_or_unknown` unless they match the explicit skip
policy. This keeps potentially valuable but unsupported files reviewable.

### Current Limitations

- Content-class assignment is heuristic and path/extension based.
- PDFs without scan path hints are flagged for text probing before trust.
- Generic images without photo or scan path hints are flagged for extraction or metadata probing.
- `binary_or_unknown` includes deferred formats such as video, shortcuts, publisher files, and other unsupported binaries.
- Checksums are optional because full-corpus checksums require reading the entire corpus.
- Semantic taxonomy classification is not implemented by this inventory gate.

## Safety Rules

- Do not delete duplicate-looking files from the NAS pass without review.
- Treat filename+size duplicate detection as conservative evidence, not final truth.
- Preserve original source path and source collection for every row.
- Keep the NAS copy as archive during MVP even after Drive import.
