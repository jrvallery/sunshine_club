# Sunshine Club Technical Architecture

## High-Level Architecture

Sunshine Club has three zones:

1. source zone
2. intelligence zone
3. canonical library zone

### Source Zone

Sources include:

- the consolidated NAS `sunshineclub` working corpus during build-out
- later, live Google Drive content in production operation
- future dashboard uploads

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

- read the unified NAS `sunshineclub` working corpus
- extract migration candidates
- support local high-compute classification
- prepare organized import into Drive

This connector is the primary source connector during Phase 1 build-out.

It is not a permanent second canonical library.

Important Phase 1 rule:

- the system works from the manually consolidated NAS `sunshineclub` folder first
- it does not begin by crawling Google Drive directly

## Core System Components

### 1. Intake

Users upload through the dashboard.

Flow:

- upload request
- file written to the universal intake folder in Drive
- ingestion job created
- status exposed to dashboard

### 2. Extraction

The extraction pipeline turns files into structured text-bearing objects.

Supported MVP paths:

- PDFs
- text
- markdown
- Google Docs
- Google Sheets
- Google Slides
- document-like images such as receipts, scans, and screenshots

Deferred:

- audio/video
- arbitrary binaries
- complex design formats
- low-value pure photos as semantic documents

### 3. Classification

Classification outputs:

- primary tag candidate
- confidence score
- top alternative tags
- summary
- document-type classification
- supporting evidence

The classifier does not choose folders directly.

### 4. Placement Resolution

Placement is computed after tag assignment.

Inputs:

- primary tag
- tag-to-folder mapping
- placement rule for that tag
- extracted metadata such as document year

Example:

- primary tag: `receipt`
- mapped folder: `Receipts`
- placement rule: `by_year`
- document year: `2026`
- final path: `Receipts/2026/`

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
- semantic relationships
- relatedness graph
- optional reranking

Retrieval is not constrained only to same-tag files.

### 8. Chat Layer

Chat can answer from:

- semantically related files
- files with different primary tags
- secondary semantic tags
- relatedness graph

Chat is grounded by citations and links.

## Tags, Folders, and Rules

### Folder Model

- top-level folders are manually created
- subfolders are manually created when needed
- folder structure should remain operationally sane, not necessarily semantically complete

### Tag Model

- tags are manually created
- one primary tag per routed file
- zero or more optional secondary semantic tags allowed
- tags live only in Sunshine Club DB

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
