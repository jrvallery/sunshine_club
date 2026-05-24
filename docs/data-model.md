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
- `source_file_id`
- `current_drive_file_id`
- `name`
- `mime_type`
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

### `document_chunks`

- `id`
- `document_id`
- `chunk_index`
- `content`
- `content_hash`
- `token_count`
- `metadata`

### `chunk_embeddings`

- `chunk_id`
- `embedding_model`
- `embedding`
- `created_at`

### `tags`

Primary controlled taxonomy.

Suggested fields:

- `id`
- `name`
- `description`
- `tag_kind`
  - `primary`
  - `secondary`
- `is_active`
- `created_by`
- `created_at`
- `updated_at`

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
- zero or more secondary semantic tags allowed

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
