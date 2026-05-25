# Sunshine Club Technical Architecture

## High-Level Architecture

Sunshine Club has three zones:

1. source zone
2. intelligence zone
3. canonical library zone

### Source Zone

Sources include:

- the consolidated NAS working corpus mounted on Atlas at `/mnt/sunshine` during build-out
- later, live Google Drive content in production operation
- future dashboard uploads

The current `/mnt/sunshine` corpus is not homogeneous. It includes:

- Google Drive-synced Sunshine shared folders
- a From Mac review pass
- Paige-local agent/workspace artifacts
- Google Drive missing/mismatch delta files
- historical archives and manifests
- a large photo and scan population alongside PDFs, Office files, text, email, spreadsheets, and presentations

### Intelligence Zone

This is Sunshine Club itself:

- extraction pipeline
- classification pipeline
- embeddings
- semantic relationships
- review state
- action state
- tag and folder mappings

### Canonical Library Zone

- final organized Google Drive corpus

## Architectural Principle

Search and chat are downstream consumers.

The core system is:

- file intelligence
- controlled tagging
- deterministic placement
- review workflow
- Drive write-back

## Connectors

### Google Drive Connector

Production connector responsibilities:

- discover files
- fetch metadata
- export Google-native docs
- download non-native files
- write organized files and moves back into Drive
- detect changes over time

This connector becomes primary after the organized corpus is imported and the production pipeline is running.

### NAS / Filesystem Connector

Build-out connector responsibilities:

- read the unified NAS working corpus at `/mnt/sunshine`
- preserve source collection, original path, size, mtime, extension, MIME type, and checksum evidence
- assign an initial content class before extraction
- extract migration candidates
- support local high-compute classification
- prepare organized import into Drive

This connector is the primary source connector during Phase 1 build-out.

It is not a permanent second canonical library.

Important Phase 1 rule:

- the system works from the manually consolidated NAS folder first
- on Atlas, that folder is mounted as `/mnt/sunshine`
- it does not begin by crawling Google Drive directly

Source areas under `/mnt/sunshine` must remain distinguishable in metadata:

- `Sunshine shared folders/`
- `From Mac Sunshine Pass 2026-05-25/`
- `Paige Agent Sunshine Files/`
- `google-drive-delta-2026-05-25/`
- `archive-2026-05-25/`
- `_manifest/`

## Core System Components

### 1. Intake

Users upload through the dashboard.

Flow:

- upload request
- file written to the universal intake folder in Drive
- ingestion job created
- status exposed to dashboard

### 2. Extraction

The extraction pipeline turns files into auditable structured extraction artifacts.

Architectural rule:

- inventory assigns an initial `content_class`
- extraction path is chosen from that class
- OCR or document parsing returns text, quality metadata, warnings, and a normalized structured payload
- the current `content_class` may be revised after extraction reveals better evidence
- Sunshine Club stores the extraction artifact before classification
- classifier scores tags from the extracted evidence and quality signals
- deterministic routing remains tag + mapping + placement rule, not an OCR-model decision

Supported MVP paths:

- PDFs
- text
- markdown
- Word documents
- spreadsheets and CSV/TSV files
- presentations
- email files
- Google Docs
- Google Sheets
- Google Slides
- document-like images such as receipts, scans, scrapbook pages, and screenshots
- TIFF/JPEG/PNG/HEIC image files with explicit photo-vs-scan routing

Deferred:

- audio/video
- arbitrary binaries
- complex design formats
- low-value pure photos as semantic documents

Content-class routing:

- born-digital documents use Docling first
- scanned PDFs, TIFFs, and document-like images use OCR as a primary extraction path
- spreadsheets preserve workbook/sheet structure and date-like columns
- emails preserve headers, body, attachments, and dates
- photos prioritize EXIF/captured date, folder context, event inference, and deterministic photo placement
- manifests and code/workspace artifacts are retained for audit/provenance but excluded from normal user search/chat unless explicitly promoted

OCR artifacts must preserve:

- raw extracted text
- normalized pages, blocks, paragraphs, and tables when available
- page numbers and coordinates when available
- extractor/model name and version
- preprocessing decisions such as rotation, deskew, contrast, and page splitting
- confidence and detected-language signals when available
- warnings such as low contrast, handwriting, skew, empty text, or mostly-image pages

Low-quality extraction lowers classifier trust and can force review.

### 3. Classification

Classification outputs:

- primary tag candidate
- confidence score
- top alternative tags
- summary
- secondary facet candidates, including record type, function, program/project/event, source collection, privacy/access, processing status, usage, and reviewer role
- supporting evidence

The classifier does not choose folders directly.

The Verdify taxonomy seed in `docs/` is the current controlled vocabulary. Primary tags are routing tags. Secondary tags are faceted metadata, not one flat semantic list.

### 4. Placement Resolution

Placement is computed after tag assignment.

Inputs:

- primary tag
- tag-to-folder mapping
- placement rule for that tag
- extracted metadata such as document year

Example:

- primary tag: `donations_receipts_fundraising`
- mapped folder: `02_Finance_Donations`
- placement rule: `by_year`
- document year: `2026`
- final path: `02_Finance_Donations/2026/`

### 5. Review System

Review queues include:

- low-confidence tag assignment
- duplicate review
- possible misfiled historical file
- missing destination folder
- taxonomy or mapping migration batches

### 6. Drive Action Engine

Actions happen in two steps:

1. store classification result
2. enqueue Drive action

Action lifecycle:

- `pending`
- `applied`
- `failed`
- `rolled_back`

Actions include:

- move file
- copy/import NAS file into Drive
- create folder only when explicitly admin-configured or approved later
- rollback move

### 7. Retrieval Layer

Retrieval uses:

- embeddings
- tag filters
- secondary facet filters
- privacy/access filters
- semantic relationships
- relatedness graph
- optional reranking

Retrieval is not constrained only to same-tag files.
Normal retrieval must exclude files whose privacy/access or processing status disallows the requesting user or workflow.

### 8. Chat Layer

Chat can answer from:

- semantically related files
- files with different primary tags
- secondary facet tags
- relatedness graph

Chat is grounded by citations and links.

## Tags, Folders, and Rules

### Folder Model

- top-level folders are manually created
- subfolders are manually created when needed
- folder structure should remain operationally sane, not necessarily semantically complete

### Tag Model

- tags are controlled by admins
- the initial V1 taxonomy is seeded from the admin-approved Verdify JSON/workbook
- later tag additions and mapping changes remain admin-controlled
- one primary tag per routed file
- zero or more optional secondary facet tags allowed
- secondary tags must carry a facet/tag group such as `record_type`, `function`, `program_project_event`, `source_collection`, `privacy_access`, `processing_status`, `usage`, or `reviewer_role`
- tags live only in Sunshine Club DB
- privacy/access is enforced as policy metadata even when it is also represented as a facet

### Mapping Model

- each primary tag maps to exactly one canonical top-level folder
- many tags may map to the same folder
- each primary tag must have one explicit placement rule

### Placement Rules

Supported MVP rule types:

- `flat`
- `by_year`
- `by_year_month` later if needed

Rules are deterministic and admin-managed.

## Dashboard as the Primary Front Door

Because users ideally never browse Drive directly, the dashboard is the real UX.

It must support:

- upload
- processing visibility
- search
- chat
- tags
- related files
- admin review
- action history

## Processing Status Model

User-visible states:

- `uploaded`
- `ingesting`
- `classifying`
- `awaiting_review`
- `routed`
- `failed`

## Visibility Rules

- intake files are not visible in normal user search/chat before completion
- at most, users see limited processing state tied to their uploads
- ignored files are excluded from normal user-facing surfaces

## Learning Loop

Files should not become trusted training signals until they have cleared routing or review.

The system stores:

- candidate tags and scores
- final human decision
- whether a new tag was created
- whether the file was ignored
- whether it was treated as duplicate
- reviewer and timestamp

## Explainability Requirements

Every tag assignment or suggestion should store:

- chosen primary tag
- confidence score
- top alternative tags
- short explanation
- similar files or evidence

## Error Handling Rules

### Missing Folder

- no fallback destination guessing
- route to admin error state

### Manual Drive Drift

- physical location disagreement does not silently rewrite tags
- create review task instead

### Mapping Changes

- changing a tag-to-folder mapping creates a controlled migration batch
- no immediate silent bulk move

### Duplicates

- duplicates block normal routing
- review decides canonical handling
