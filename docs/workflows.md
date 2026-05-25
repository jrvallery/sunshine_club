# Sunshine Club Workflows

## 1. Historical Google Drive Cleanup

This workflow only begins after the staged corpus has been organized locally and imported into Drive.

For initial build-out, existing Drive material should first be copied into `/mnt/sunshine` instead of being processed live from Drive.

Steps:

1. ingest existing Drive files
2. extract text and metadata
3. classify to a primary routing tag and optional secondary facets
4. detect possible duplicates
5. compare current location with expected tag-based location
6. create review tasks for:
   - low-confidence items
   - duplicates
   - possible misfiled files
7. after admin approval, enqueue move actions

Important rule:

- historical files are never broadly reorganized without review

## 2. NAS Staging and Migration

This workflow is the initial build-out workflow.

Before implementation begins, all existing source material is manually consolidated into one NAS folder:

- `/mnt/sunshine`

This includes:

- copied or exported material from the current Google Drive
- NAS / Obsidian material
- other scattered source files
- the From Mac review pass
- Google Drive delta files that were missing or mismatched locally
- Paige-local agent/workspace artifacts
- inventory and comparison manifests

The system then treats `/mnt/sunshine` as the Phase 1 working corpus.

Steps:

1. read the unified `/mnt/sunshine` corpus
2. assign source collection and initial content class from path, MIME type, extension, and manifest evidence
3. extract metadata, text, quality, warnings, and normalized page/block/table payload through the appropriate content-class path
4. revise content class when extraction evidence proves the initial class was wrong
5. classify files into the same tag system when the content class is semantically routable
6. detect duplicates inside the staged corpus
7. determine intended Google Drive destination for each kept file
8. prepare organized import actions into Drive
9. keep original NAS copies during MVP

Important rules:

- Drive becomes canonical after organized import
- original NAS content is retained as archive during MVP
- imported files do not delete or rewrite originals automatically

## 3. User Upload Intake

This is the steady-state flow for new files.

Steps:

1. user uploads file through the dashboard
2. file is written immediately into the universal intake folder in Drive
3. upload job enters processing queue
4. system extracts and classifies file
5. if duplicate ambiguity exists, create duplicate review task
6. if confidence is below threshold or margin is too small, create review task
7. if confidence, separation, privacy policy, and processing status are safe enough:
   - assign primary routing tag
   - assign optional secondary facets
   - assign or derive privacy/access, processing status, usage, and reviewer role policy
   - persist classification result
   - enqueue move action
8. file is moved into canonical destination

## 4. Duplicate Review

The duplicate workflow handles:

- exact duplicates
- near duplicates
- possible newer versions

Admin decisions:

- keep existing canonical file and suppress new item
- keep both as distinct items
- treat new item as newer replacement

Files in duplicate review do not enter normal routing or learning until resolved.

## 5. Low-Confidence Review

Admin can:

- assign an existing primary tag
- create a new primary tag
- leave a note
- retry classification
- mark ignore

## 6. Ignore Workflow

If a file is ignored:

- it enters a terminal ignored state
- it is excluded from:
  - auto-routing
  - learning
  - normal search
  - normal chat

Ignored files may remain visible in admin-only views.

## 7. Misfiled File Review

If a file's current Drive folder does not match the folder implied by its primary tag:

1. detect mismatch on ingest or reconciliation
2. create review task
3. admin decides whether:
   - tag should change
   - mapping should change
   - file should move back

## 8. Tag Mapping Change Workflow

When an admin changes the folder mapped to a primary tag:

1. create a migration batch
2. compute affected file count
3. show conflicts or blocked items
4. after approval, enqueue bulk move actions
5. track progress and failures separately

## 9. Missing Destination Workflow

If a file is routed by a tag whose folder mapping is broken:

1. store semantic assignment
2. block move execution
3. create admin error task
4. wait for admin to:
   - relink tag to an existing folder
   - or create the intended folder manually

## 10. Search Workflow

Search should support:

- natural-language semantic search
- explicit tag filtering
- secondary facet filtering
- related file discovery
- open-in-Drive links

Ignored and unresolved intake items are excluded from normal user search.
Restricted, donor-sensitive, beneficiary-sensitive, treasurer-only, legal/IRS-sensitive, member-private, and system-admin files are also excluded unless the user and workflow are authorized.

## 11. Chat Workflow

Chat should:

- answer from the full semantic graph
- use citations and links
- not be restricted to same-tag files only
- explain why a file is related or how it was routed
- obey the same privacy/access and processing-status filters as search

## 12. Taxonomy and Facet Workflow

The Verdify handoff in `docs/` is the current taxonomy source of truth.

Steps:

1. seed canonical folders, primary tags, secondary facet values, placement rules, default privacy, and reviewer roles from the Verdify JSON/workbook
2. keep one applied primary routing tag per routed file
3. assign secondary facet values for record type, function, program/project/event, source collection, privacy/access, processing status, usage, and reviewer role
4. enforce privacy/access as policy, not only as a visible tag
5. use the handoff retrieval questions and golden examples as classifier and retrieval acceptance tests
6. freeze a taxonomy version only after a 50-100 item golden sample is hand-labeled and passes review

## 13. Photo Workflow

For low-text photos:

- skip semantic tagging when extraction is too weak
- route with the `historical_photos` primary tag when the item is a true photo/media record
- example:
  - `06_History_Archive/{captured_year or upload_year}`
- use EXIF/captured dates, folder context, event names, and filename clues before falling back to upload/import date
- keep scan-like TIFF/JPEG/PDF files eligible for OCR before deciding they are pure photos
- allow OCR to upgrade an initial `image` classification to `scanned_document` when text/layout evidence is strong

These should not be forced into normal text-centric semantic routing.

## 14. Manifest and Workspace Artifact Workflow

Manifest, log, comparison, code, and workspace artifact files are useful for audit and provenance, but most should not appear in normal user-facing search or chat.

Steps:

1. ingest the file with source collection and original path preserved
2. assign `manifest` or `code_or_workspace_artifact` content class
3. store extraction output only if it helps audit, debugging, or lineage
4. exclude from normal search/chat unless an admin explicitly promotes the file
