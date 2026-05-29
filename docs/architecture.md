# Sunshine Club Architecture

Last updated: 2026-05-28.

## Product Summary

Sunshine Club is a Google Drive organization system with semantic intelligence.

This repo is **Track A: archive and Google Drive intelligence**. It classifies scattered documents from Google Drive and the NAS staging corpus into a controlled tag model, routes them into the right Google Drive folders, keeps future uploads organized when confidence is high, and exposes search, related discovery, and grounded chat on top.

It is not a generic RAG app and should not silently expand into donor CRM, receipt automation, event management, governance survey execution, or anniversary project management unless those tracks are explicitly scoped.

## Build-Out Corpus Strategy

Existing source material is consolidated into one NAS working root on Atlas:

- `/mnt/sunshine`

This corpus contains: copied/exported Google Drive material, NAS/Obsidian material, From Mac review-pass files, Google Drive delta files (missing/mismatched locally), Paige-local agent/workspace artifacts and manifests, and other staged files.

Phase 1 operates on `/mnt/sunshine` as the working corpus. Google Drive remains the canonical production destination after organization and import.

## Canonical Product Decisions

### Source of Truth

- Google Drive is the canonical production library.
- Sunshine Club DB is the source of truth for semantic state.
- Tags do not live in Google Drive metadata.
- Original NAS/source copies are retained during MVP import.

### User Experience

- Users ideally never browse Drive directly — the dashboard is the real product surface.
- Users upload through the dashboard, not by choosing final folders themselves.
- Users can view all tags on a file. Users cannot directly edit tags in MVP.

### Roles

- Initial operator: James only.
- End users later: upload files, search, chat, browse tags and related items.

### Tag Hierarchy

- Every routed file has exactly one **primary tag** (controls routing intent).
- Files may have zero or more optional **secondary facet tags** (for retrieval, filtering, explanation, privacy, review routing, source provenance, output usage).
- Secondary facets are grouped by facet type — not one undifferentiated pile.
- Required V1 facet groups: `record_type`, `function`, `program_project_event`, `source_collection`, `privacy_access`, `processing_status`, `usage`, `reviewer_role`.
- Objective subfolders like year are rule-derived metadata outputs, not free-form AI taxonomy.

### Folder and Tag Control

- Folders are manually created. Top-level and subfolders are manually created.
- V1 taxonomy terms are seeded from the admin-approved Verdify taxonomy files in `docs/`.
- New tags are manually created through admin control only.
- Tags are manually mapped to folders. Many tags may map to one folder.
- Each primary tag resolves to exactly one canonical top-level folder.
- Each primary tag must have an explicit placement rule.

### Placement Rules

- Primary tag determines the top-level folder family.
- Placement rules determine whether files land: flat, by-year, or by-year-month subfolder.
- Objective subfolders are derived from document date, captured year, or upload year.
- If a primary tag has no placement rule, files with that tag cannot auto-route.

### Classifier Scope

- The classifier only decides the best primary tag candidate and confidence.
- The classifier does not invent folders or directly choose the final path.
- Placement after tag assignment is deterministic: tag → mapping → placement rule.

### Automation Rules

- May automatically: ingest, classify, summarize, embed, propose actions.
- May auto-route new files only when confidence is high enough.
- May **not** bulk reorganize existing files without human review.
- May **never** automatically delete files in MVP.

### Confidence Rules

- Absolute confidence threshold required.
- Margin from runner-up tag also required.
- If top and second-best tags are too close, route to review.

### Review Rules

- Low-confidence files go to manual review.
- Manual review can: assign existing primary tag, create new tag, leave note, mark ignore, retry classification.
- Ignored files are excluded from routing, learning, normal search, and normal chat.
- Privacy-sensitive files (donor, member-private, beneficiary, legal/IRS, treasurer-only) excluded from normal search/chat unless explicitly allowed.

Additional review reasons: privacy review, date confirmation, person identification, source verification, publication approval, family-return review.

### Duplicate Rules

- Duplicate review must distinguish: exact duplicate, near duplicate, possible newer version.
- MVP versions handled through duplicate review decisions, not a full lineage graph.

### Learning and Drift Rules

- System learns from human review decisions (approved = positive signal, rejected = negative).
- Hard rules remain authoritative. MVP learning is retrieval/example-based, not fine-tuning.
- Manual Drive moves do not silently rewrite tags — create a review task instead.
- If a tag-to-folder mapping changes, affected files create a reviewable migration batch first.
- If a tag's destination folder is missing, route to admin error state — do not guess.

## System Architecture

### Three Zones

1. **Source Zone** — NAS `/mnt/sunshine` during build-out; later live Google Drive + dashboard uploads.
2. **Intelligence Zone** — Sunshine Club itself: extraction, classification, embeddings, review state, action state, tag and folder mappings.
3. **Canonical Library Zone** — final organized Google Drive corpus.

### Architectural Principle

Search and chat are **downstream consumers**. The core system is: file intelligence → controlled tagging → deterministic placement → review workflow → Drive write-back.

### Local Container Topology

Default services (Docker Compose):

- `api` — FastAPI admin and product API (port 8000)
- `dashboard` — Next.js admin dashboard (port 3000)
- `db` — Postgres + pgvector, seeded from `infra/db/migrations` (port 5432)
- `temporal` — local Temporal server (port 7233)
- `temporal-ui` — Temporal inspection UI (port 8080)
- `worker` — opt-in Compose profile; joins default stack after Temporal workflow registration is implemented.
- `qdrant` — local vector search for chunks and labeled examples (port 6333, V2)

The NAS source root mounts read-only into containers at `/mnt/sunshine`. Override path with `SUNSHINE_NAS_ROOT`.

### Core Pipeline Steps

1. **Intake** — User uploads through dashboard → file written to Drive intake folder → ingestion job created.
2. **Extraction** — inventory assigns initial `content_class` → extraction path chosen from class → OCR/parsing returns text, quality metadata, warnings, normalized payload → content_class may be revised.
3. **Classification** — outputs: primary tag candidate, confidence, top alternatives, summary, secondary facet candidates, supporting evidence. Classifier does not choose folders.
4. **Placement Resolution** — primary tag + tag-folder mapping + placement rule + extracted metadata → deterministic destination path.
5. **Review System** — queues: low-confidence, duplicate, misfiled, missing destination, migration batches, privacy, date, person-id, source-verification, publication-approval, family-return.
6. **Drive Action Engine** — store classification result, then enqueue Drive action. Actions: `pending → applied → failed → rolled_back`.
7. **Retrieval Layer** — embeddings, tag filters, secondary facet filters, privacy/access filters, semantic relationships, relatedness graph.
8. **Chat Layer** — grounded by citations and links; not constrained to same-tag files.

### Connectors

**NAS/Filesystem Connector** (Phase 1 primary): read `/mnt/sunshine`, preserve source collection/path/size/mtime/extension/MIME/checksum, assign initial content class, extract migration candidates.

Source areas under `/mnt/sunshine`:
- `Sunshine shared folders/`
- `From Mac Sunshine Pass 2026-05-25/`
- `Paige Agent Sunshine Files/`
- `google-drive-delta-2026-05-25/`
- `archive-2026-05-25/`
- `_manifest/`

**Google Drive Connector** (becomes primary after organized import): discover files, fetch metadata, export native docs, download non-native files, write organized files and moves back into Drive, detect changes over time.

### Processing Status Model

User-visible states: `uploaded` → `ingesting` → `classifying` → `awaiting_review` → `routed` → `failed`.

## Technical Stack

| Layer | Technology | Role |
|---|---|---|
| API | FastAPI + Uvicorn | Admin and product API; dashboard backend |
| Dashboard | Next.js app router | Admin review/runs/files UI |
| Workflow orchestration | LangGraph | Controlled decision graph (extraction → classification → review → routing) |
| Durable execution | Temporal | Long-running batch jobs, review waits, import workflows |
| Database | Postgres + pgvector | Canonical operational truth and vector retrieval |
| Vector search | Qdrant (V2) | Local vector search for chunks and labeled examples |
| Observability | OpenTelemetry + Langfuse | Request/workflow/model call tracing, cost tracking |
| Document parsing | Docling | Born-digital documents and office files |
| OCR | OCRmyPDF + Tesseract (+ Docling OCR) | Scanned PDFs, TIFFs, document-like images |
| OCR fallback | Cortex OCR | Escalation path for poor/empty local OCR |
| Optional parser | Marker | Benchmark/fallback path; not the primary baseline |

**Key architectural rules:**
- LangGraph manages flow logic; Temporal manages durable execution and resumption — these layers solve different problems.
- Structured application state belongs in Postgres first. Do not depend on a separate memory product as the core state layer in V1.
- Runtime guards are first-class: max workflow steps, max repeated tool-call signatures, token/cost budgets, retry budgets per document/batch, dead-letter handling, idempotency for Drive actions, circuit breakers, admin kill switches.

**Acceptable substitutions:** Prefect instead of Temporal if ops burden is too high; Arize Phoenix instead of/alongside Langfuse; Unstructured as parser path for specific sources.

**Not the baseline:** Mem0/Letta/Zep as core state, CrewAI/AutoGen-style swarms, framework-only observability, single-parser lock-in.

## Taxonomy

Last aligned: 2026-05-25. Taxonomy source of truth: `docs/Sunshine_Taxonomy_Seed_v0.1_2026-05-25.json` and `docs/Sunshine_Taxonomy_v0.1_Workbook_2026-05-25.xlsx`.

**Handoff rule (authoritative):**
- *Folders* answer: where should a human volunteer expect this file to live?
- *Primary routing tag* answers: which single folder family should the system route toward?
- *Secondary facets* answer: what is it, what does it concern, where did it come from, who may see it, what review it needs, what outputs may use it.

Do **not** build a deep folder tree like `History > 1930s > Dental > Rotary`. Sunshine records overlap too much. One primary routing tag per file; rich secondary facets in the DB.

### Canonical Folder Families

| Folder key | Drive folder | Default privacy |
|---|---|---|
| `00_read_me_runbooks` | `00_READ_ME_AND_RUNBOOKS` | `club_internal` |
| `01_governance_admin` | `01_Governance_Admin` | `board_only` |
| `02_finance_donations` | `02_Finance_Donations` | `treasurer_only` |
| `03_membership` | `03_Membership` | `member_private` |
| `04_programs_partnerships` | `04_Programs_Partnerships` | `club_internal` |
| `05_events` | `05_Events` | `club_internal` |
| `06_history_archive` | `06_History_Archive` | `club_internal` |
| `07_communications` | `07_Communications` | `club_internal` |
| `08_operations_assets` | `08_Operations_Assets` | `club_internal` |
| `09_125th_anniversary` | `09_125th_Anniversary` | `club_internal` |
| `90_intake_needs_review` | `90_Intake_Needs_Review` | `restricted` |
| `99_system_exports_logs` | `99_System_Exports_Logs` | `system_admin` |

### Primary Routing Tags

| Primary tag | Folder key | Placement rule | Default privacy |
|---|---|---|---|
| `runbooks_handoff` | `00_read_me_runbooks` | `flat` | `club_internal` |
| `governance_bylaws_policy` | `01_governance_admin` | `flat` | `board_only` |
| `meeting_records` | `01_governance_admin` | `by_year` | `club_internal` |
| `finance_treasurer_records` | `02_finance_donations` | `by_year` | `treasurer_only` |
| `donations_receipts_fundraising` | `02_finance_donations` | `by_year` | `donor_sensitive` |
| `membership_rosters_yearbooks` | `03_membership` | `by_year` | `member_private` |
| `dental_program` | `04_programs_partnerships` | `by_year` | `club_internal` |
| `senior_smiles` | `04_programs_partnerships` | `by_year` | `club_internal` |
| `scholarships` | `04_programs_partnerships` | `by_year` | `beneficiary_sensitive` |
| `partner_programs` | `04_programs_partnerships` | `by_year` | `club_internal` |
| `annual_spring_tea` | `05_events` | `by_year` | `club_internal` |
| `other_events` | `05_events` | `by_year` | `club_internal` |
| `history_archive_general` | `06_history_archive` | `by_year` | `club_internal` |
| `scrapbooks` | `06_history_archive` | `by_year` | `club_internal` |
| `historical_photos` | `06_history_archive` | `by_year` | `club_internal` |
| `press_publications` | `06_history_archive` | `by_year` | `public` |
| `communications_templates` | `07_communications` | `flat` | `club_internal` |
| `website_public_materials` | `07_communications` | `flat` | `public` |
| `operations_assets` | `08_operations_assets` | `flat` | `club_internal` |
| `legal_insurance_compliance` | `08_operations_assets` | `by_year` | `legal_irs_sensitive` |
| `anniversary_125th` | `09_125th_anniversary` | `flat` | `club_internal` |
| `cookbook_project` | `09_125th_anniversary` | `flat` | `club_internal` |
| `documentary_project` | `09_125th_anniversary` | `flat` | `club_internal` |
| `central_garden_project` | `09_125th_anniversary` | `flat` | `club_internal` |
| `system_exports_logs` | `99_system_exports_logs` | `by_year_month` | `system_admin` |

### Required Secondary Facets

Supported V1 secondary facet groups: `record_type`, `function`, `program_project_event`, `source_collection`, `privacy_access`, `processing_status`, `usage`, `reviewer_role`.

Privacy/access is **policy metadata**, not merely a search tag. Records marked `donor_sensitive`, `member_private`, `beneficiary_sensitive`, `legal_irs_sensitive`, `treasurer_only`, `system_admin`, or unresolved `restricted` must be excluded from normal search/chat unless the requesting user and workflow are explicitly allowed.

V1 must seed the taxonomy from `docs/Sunshine_Taxonomy_Seed_v0.1_2026-05-25.json` rather than manual re-entry from prose.

## Success Metrics

Primary (operational): percentage of new files routed correctly without correction, review burden trend over time, duplicate pollution rate, stability of tag usage and mappings.

Secondary: search usefulness, chat usefulness, review turnaround time, failed action rate.
