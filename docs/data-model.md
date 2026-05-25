# Sunshine Club Data Model

## Design Principle

The schema must distinguish:

- semantic state
- physical file location
- review state
- action state

Semantic assignment and physical movement are not the same thing.

## Core Entities

### `documents`

Represents every known file.

Suggested fields:

- `id`
- `source_type`
  - `google_drive`
  - `nas`
  - `upload`
- `source_collection`
  - `sunshine_shared_folders`
  - `from_mac_pass`
  - `paige_agent_files`
  - `google_drive_delta`
  - `archive`
  - `manifest`
  - `other`
- `source_collection_label`
  - optional Verdify source collection facet such as `Green Scrapbook`, `Yearbooks`, `Slack Upload`, `NAS Working Corpus`, `Google Drive Current Folder`, or `Budget Review 2016-2026`
- `source_file_id`
- `source_path`
- `current_drive_file_id`
- `name`
- `mime_type`
- `extension`
- `size_bytes`
- `source_mtime`
- `content_class`
  - `document`
  - `image`
  - `scanned_document`
  - `spreadsheet`
  - `presentation`
  - `email`
  - `google_native_export`
  - `manifest`
  - `code_or_workspace_artifact`
  - `binary_or_unknown`
- `checksum`
- `raw_metadata`
- `status`
  - `discovered`
  - `processing`
  - `awaiting_review`
  - `routed`
  - `ignored`
  - `duplicate_hold`
  - `failed`
- `is_canonical`
- `created_at`
- `updated_at`

Rules:

- `source_collection` records which mounted corpus area or incoming batch produced the row.
- `source_collection_label` or the equivalent secondary `source_collection` facet records the human/archive collection from the Verdify taxonomy.
- `source_path`, `size_bytes`, `source_mtime`, `extension`, and `checksum` are provenance and duplicate signals, not semantic classification by themselves.
- `content_class` is the current best class. It is assigned during inventory and may be revised after extraction reveals better evidence.
- Manifest and workspace artifact rows may be retained for audit/provenance while being excluded from normal user search/chat.

Example revision:

- a file starts as `image`
- OCR/preprocessing shows it is a receipt or scanned meeting notes
- the current `content_class` can be upgraded to `scanned_document`

### `extraction_artifacts`

Stores normalized output from OCR and document parsers.

Suggested fields:

- `id`
- `document_id`
- `extractor`
- `extractor_version`
- `content_class_before`
- `content_class_after`
- `text`
- `normalized_payload`
- `quality`
  - `stub`
  - `empty`
  - `ok`
  - `poor`
- `warnings`
- `metadata`
- `created_at`

Rules:

- OCR and document parsers produce extraction artifacts; they do not decide final routing.
- `normalized_payload` should preserve structured downstream evidence such as pages, blocks, paragraphs, tables, coordinates, page numbers, confidence scores, detected language, and preprocessing decisions when available.
- `content_class_before` and `content_class_after` make content-class revision auditable.
- Low-quality or warning-heavy extraction should lower classifier trust and may force review.

### `document_chunks`

- `id`
- `document_id`
- `chunk_index`
- `content`
- `content_hash`
- `token_count`
- `metadata`

Rules:

- chunks are derived from extraction artifacts after normalized extraction output exists.
- chunk metadata should retain page/block references so search, chat citations, and review UI can point back to source evidence.

### `chunk_embeddings`

- `chunk_id`
- `embedding_model`
- `embedding`
- `created_at`

### `tags`

Primary controlled taxonomy.

Suggested fields:

- `id`
- `tag_key`
- `display_name`
- `description`
- `tag_kind`
  - `primary`
  - `secondary`
- `facet`
  - null for primary routing tags
  - `record_type`
  - `function`
  - `program_project_event`
  - `source_collection`
  - `privacy_access`
  - `processing_status`
  - `usage`
  - `reviewer_role`
- `default_privacy`
- `default_reviewer_role`
- `is_active`
- `created_by`
- `created_at`
- `updated_at`

Rules:

- `tag_key` is the stable machine key from the Verdify seed JSON when available.
- `display_name` is the human label.
- Primary tags control routing. Secondary tags must have a `facet` so record type, program, source collection, privacy, processing status, usage, and reviewer role do not collapse into one flat tag pile.
- Privacy/access may be represented as a facet for filtering, but enforceable access policy must also be persisted on the document or derived policy state.

### `folders`

Represents manually created Drive folder targets.

Suggested fields:

- `id`
- `name`
- `drive_folder_file_id`
- `parent_folder_id`
- `path_hint`
- `is_active`
- `created_by`
- `created_at`
- `updated_at`

### `tag_folder_mappings`

Maps primary tags to canonical top-level folders.

Suggested fields:

- `id`
- `tag_id`
- `folder_id`
- `is_active`
- `created_by`
- `created_at`
- `updated_at`

Rules:

- one active mapping per primary tag
- many tags may point to the same folder

### `placement_rules`

Defines deterministic subfolder behavior for a primary tag.

Suggested fields:

- `id`
- `tag_id`
- `rule_type`
  - `flat`
  - `by_year`
  - `by_year_month`
- `date_source`
  - `document_date`
  - `captured_date`
  - `upload_date`
- `minimum_date_confidence`
- `is_active`
- `created_by`
- `created_at`
- `updated_at`

### `document_tag_assignments`

Stores applied and proposed tags.

Suggested fields:

- `id`
- `document_id`
- `tag_id`
- `assignment_role`
  - `primary`
  - `secondary`
- `status`
  - `proposed`
  - `applied`
  - `rejected`
- `confidence`
- `evidence`
- `created_at`
- `updated_at`

Rules:

- one applied primary tag per routed document
- zero or more secondary facet tags allowed
- secondary facet assignments should preserve facet type, confidence, evidence, and whether the assignment came from the Verdify seed, extraction, classifier, or human review

### `document_policy`

Stores enforceable privacy and workflow policy separate from descriptive tags.

Suggested fields:

- `id`
- `document_id`
- `privacy_access`
  - `public`
  - `club_internal`
  - `board_only`
  - `treasurer_only`
  - `donor_sensitive`
  - `member_private`
  - `beneficiary_sensitive`
  - `legal_irs_sensitive`
  - `family_return_sensitive`
  - `system_admin`
  - `restricted`
- `processing_status`
- `reviewer_role`
- `usage_allowed`
- `policy_source`
  - `taxonomy_default`
  - `classifier`
  - `human_review`
- `created_at`
- `updated_at`

Rules:

- Privacy/access is policy metadata, not merely a tag.
- Normal search/chat must exclude restricted, unresolved, donor-sensitive, beneficiary-sensitive, treasurer-only, legal/IRS-sensitive, member-private, and system-admin records unless the user and workflow are allowed.
- Public output requires explicit publication approval.

### `document_dates`

Stores date evidence and confidence for archive material.

Suggested fields:

- `id`
- `document_id`
- `date_value`
- `date_granularity`
  - `day`
  - `month`
  - `year`
  - `decade`
  - `range`
  - `unknown`
- `date_confidence`
  - `exact`
  - `inferred`
  - `approximate`
  - `range`
  - `unknown`
- `date_source`
  - `document_text`
  - `file_metadata`
  - `folder_path`
  - `exif`
  - `human_review`
- `evidence`
- `created_at`

### `classification_runs`

Captures classifier outputs for learning and audit.

Suggested fields:

- `id`
- `document_id`
- `model`
- `top_candidates`
- `top_score`
- `runner_up_score`
- `margin`
- `explanation`
- `similar_documents`
- `extraction_quality`
- `created_at`

### `document_relationships`

- `id`
- `source_document_id`
- `target_document_id`
- `relationship_type`
  - `duplicate_candidate`
  - `near_duplicate`
  - `related`
  - `same_theme`
  - `possible_newer_version`
- `score`
- `evidence`
- `created_at`

### `review_tasks`

- `id`
- `document_id`
- `task_type`
  - `low_confidence`
  - `duplicate_review`
  - `misfiled_file`
  - `missing_destination`
  - `mapping_migration`
  - `privacy_review`
  - `date_confirmation`
  - `person_identification`
  - `source_verification`
  - `publication_approval`
  - `family_return_review`
- `status`
  - `open`
  - `in_progress`
  - `resolved`
  - `dismissed`
- `payload`
- `resolution`
- `reviewer`
- `created_at`
- `updated_at`

### `human_decisions`

Structured review outcomes for bounded learning.

Suggested fields:

- `id`
- `document_id`
- `review_task_id`
- `final_primary_tag_id`
- `final_secondary_semantic_tag_ids`
- `decision_type`
  - `accepted_existing_tag`
  - `created_new_tag`
  - `ignored`
  - `duplicate_existing`
  - `keep_both`
  - `replace_with_newer`
- `note`
- `reviewer`
- `created_at`

### `drive_actions`

- `id`
- `document_id`
- `action_type`
  - `move`
  - `import_to_drive`
  - `rollback_move`
- `status`
  - `pending`
  - `applied`
  - `failed`
  - `rolled_back`
- `from_path`
- `to_path`
- `payload`
- `result`
- `error_message`
- `created_at`
- `started_at`
- `finished_at`

### `migration_batches`

Used when changing tag mappings or importing staged files.

Suggested fields:

- `id`
- `batch_type`
  - `tag_mapping_change`
  - `nas_import`
- `status`
  - `draft`
  - `approved`
  - `running`
  - `completed`
  - `failed`
- `summary`
- `payload`
- `created_by`
- `created_at`
- `updated_at`

## Search and Chat Visibility Rules

Normal user-facing search and chat should exclude:

- ignored files
- duplicate-hold files
- unresolved intake items
- failed items

Admin views may expose them with explicit filters.
