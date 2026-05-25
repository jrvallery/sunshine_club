# Sunshine Club Product Spec

## Product Summary

Sunshine Club is a Google Drive organization system with semantic intelligence.

The product is not a generic RAG app.

Per the Verdify handoff, this repo is Track A: archive and Google Drive intelligence. It should not silently expand into donor CRM, receipt automation, event management, governance survey execution, correspondence operations, or anniversary project management unless those tracks are explicitly scoped later.

Its primary purpose is to:

- take scattered documents from Google Drive and the NAS staging corpus
- classify them into a controlled tag model
- route them into the right Google Drive folders
- keep future uploads organized automatically when confidence is high
- expose search, related discovery, and grounded chat on top

## Build-Out Corpus Strategy

Existing source material is consolidated into one NAS working root on Atlas:

- `/mnt/sunshine`

This build-out corpus will contain:

- copied or exported material from the current Google Drive
- NAS / Obsidian material
- From Mac review-pass files
- Google Drive delta files that were missing or mismatched locally
- Paige-local agent/workspace artifacts and manifests
- other relevant staged files

This means:

- Phase 1 does not pull source files directly from Google Drive
- Phase 1 operates on `/mnt/sunshine` as the working corpus
- Phase 1 must handle a photo-heavy corpus with scans, documents, spreadsheets, email, manifests, and workspace artifacts
- Google Drive remains the canonical production destination after organization and import

## Canonical Product Decisions

These are current baseline decisions.

### Source of Truth

- Google Drive is the canonical production library.
- Sunshine Club's database is the source of truth for semantic state.
- Tags do not live in Google Drive metadata.
- During build-out, existing source material is first consolidated into `/mnt/sunshine` and treated as the working corpus.
- Original NAS/source copies are retained during MVP import and migration work.

### User Experience

- In the ideal end state, users rarely or never browse Drive directly.
- The dashboard is the real product surface.
- Users upload through the dashboard, not by choosing final folders themselves.
- Users can view all tags on a file.
- Users cannot directly edit tags in MVP.
- Users should be able to search semantically and also filter by tags.

### Roles

- Initial operator: James only.
- End users later:
  - upload files
  - search
  - chat
  - browse tags and related items
  - occasionally suggest or request corrections

### Folder and Tag Control

- Folders are manually created.
- Top-level folders are manually created.
- Subfolders are also manually created where needed.
- Tags are manually created.
- Only James creates tags.
- Tags are manually mapped to folders.
- Many tags may map to one folder.
- Each primary tag resolves to exactly one canonical top-level folder.
- Each primary tag must also have an explicit placement rule.

### Tag Hierarchy

- Every routed file has exactly one primary tag.
- Files may have zero or more optional secondary facet tags.
- Primary tag controls top-level routing intent.
- Secondary facets are for retrieval, relatedness, filtering, explanation, privacy, review routing, source provenance, and output usage.
- Secondary facets are grouped by facet type, not stored as one undifferentiated pile.
- Required V1 facet groups are:
  - `record_type`
  - `function`
  - `program_project_event`
  - `source_collection`
  - `privacy_access`
  - `processing_status`
  - `usage`
  - `reviewer_role`
- Objective subfolders such as year are rule-derived metadata outputs, not free-form AI taxonomy.

The current taxonomy source of truth is the Verdify handoff in `docs/taxonomy-handoff/`, summarized in `docs/taxonomy.md`.

### Placement Rules

- Primary tag determines the top-level folder family.
- Placement rules determine whether files land:
  - flat under that folder
  - in a year-based subfolder
  - in a year-month-based subfolder later if needed
- Objective subfolders are derived from metadata such as:
  - document date
  - captured year
  - upload year
- If a primary tag has no placement rule, files with that tag cannot auto-route.

### Classifier Scope

- The classifier only decides the best primary tag candidate and confidence.
- The classifier does not invent folders.
- The classifier does not directly choose the final folder path.
- Placement after tag assignment is deterministic based on:
  - tag-to-folder mapping
  - placement rules

### Automation Rules

- The system may automatically:
  - ingest
  - classify
  - summarize
  - embed
  - propose actions
- It may auto-route new files only when confidence is high enough.
- It may not bulk reorganize existing files without human review.
- It may never automatically delete files in MVP.

### Confidence Rules

- Absolute confidence threshold is required.
- Margin from the runner-up tag is also required.
- If the top tag and second-best tag are too close, route to review.
- Confidence can control routing in MVP.
- Poor extraction quality and duplicate ambiguity still block trusted outcomes.

### Review Rules

- Low-confidence files go to manual review.
- Manual review can:
  - assign an existing primary tag
  - create a new tag
  - leave a note
  - mark ignore
  - retry classification
- Ignored files are excluded from:
  - routing
  - learning
  - normal search
  - normal chat
- Privacy-sensitive, beneficiary-sensitive, donor-sensitive, legal/IRS-sensitive, treasurer-only, and unresolved restricted files are excluded from normal search/chat unless the current user and workflow are explicitly allowed.

Additional review reasons from the Verdify handoff:

- privacy review
- date confirmation
- person identification
- source verification
- publication approval
- family-return review

### Duplicate Rules

- Duplicate handling is required for uploads and NAS migration.
- Duplicate review must distinguish:
  - exact duplicate
  - near duplicate
  - possible newer version
- For MVP, versions are handled through duplicate review decisions rather than a full lineage graph.

### Learning Rules

- The system should learn from human review decisions.
- Approved actions are positive signals.
- Rejected actions are negative signals.
- Hard rules remain authoritative.
- MVP learning is retrieval- and example-based, not fine-tuning.

### Drift Rules

- Manual Drive moves do not silently rewrite tags.
- If a file's physical location disagrees with its assigned primary tag, create a review task.

### Mapping Change Rules

- If a tag-to-folder mapping changes, affected files should move to the new mapped location.
- Mapping changes create a reviewable migration batch first.
- Bulk movement should not happen silently on mapping edit.

### Missing Destination Rules

- If a tag's destination folder is missing, the system must not guess.
- Routing enters an admin error state until the tag is re-linked or the folder is recreated.

## User Stories

### Admin / Operator Stories

- As an admin, I want to define folders manually so the Drive structure stays intentional.
- As an admin, I want to define tags manually so the taxonomy stays controlled.
- As an admin, I want to map tags to folders so file routing is deterministic.
- As an admin, I want low-confidence files to enter review instead of being guessed into place.
- As an admin, I want duplicate uploads to enter duplicate review instead of polluting the library.
- As an admin, I want to review possible misfiled historical files and correct them safely.
- As an admin, I want changing a tag mapping to create a controlled migration batch.
- As an admin, I want to see why the system assigned a tag so I can calibrate it.
- As an admin, I want all review actions stored so the system can learn later.

### End User Stories

- As a user, I want to upload a file through the dashboard without choosing a final Drive folder.
- As a user, I want to see whether my file is uploaded, processing, awaiting review, routed, or failed.
- As a user, I want to search the corpus semantically and open the right file quickly.
- As a user, I want to see all tags attached to a file.
- As a user, I want to filter by tags as well as use natural-language search.
- As a user, I want to ask questions in chat and get grounded answers with links.
- As a user, I want to see related files even when they do not share the same primary tag.

## Success Metrics

The main MVP success metric is operational, not chat quality.

Primary metrics:

- percentage of new files routed correctly without human correction
- review burden trend over time
- duplicate pollution rate
- stability of tag usage and tag-to-folder mappings

Secondary metrics:

- search usefulness
- chat usefulness
- review turnaround time
- failed action rate
