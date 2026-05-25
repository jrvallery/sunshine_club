CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_type text NOT NULL CHECK (source_type IN ('google_drive', 'nas', 'upload')),
  source_file_id text,
  source_path text,
  current_drive_file_id text,
  name text NOT NULL,
  mime_type text NOT NULL,
  checksum text,
  raw_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL CHECK (status IN ('discovered', 'processing', 'awaiting_review', 'routed', 'ignored', 'duplicate_hold', 'failed')),
  is_canonical boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE document_chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index integer NOT NULL,
  content text NOT NULL,
  content_hash text NOT NULL,
  token_count integer,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_id, chunk_index)
);

CREATE TABLE chunk_embeddings (
  chunk_id uuid NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
  embedding_model text NOT NULL,
  embedding vector,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (chunk_id, embedding_model)
);

CREATE TABLE tags (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL UNIQUE,
  description text,
  tag_kind text NOT NULL CHECK (tag_kind IN ('primary', 'secondary')),
  is_active boolean NOT NULL DEFAULT true,
  created_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE folders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  drive_folder_file_id text NOT NULL UNIQUE,
  parent_folder_id uuid REFERENCES folders(id),
  path_hint text NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  created_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tag_folder_mappings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tag_id uuid NOT NULL REFERENCES tags(id),
  folder_id uuid NOT NULL REFERENCES folders(id),
  is_active boolean NOT NULL DEFAULT true,
  created_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX one_active_mapping_per_primary_tag
  ON tag_folder_mappings(tag_id)
  WHERE is_active;

CREATE TABLE placement_rules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tag_id uuid NOT NULL REFERENCES tags(id),
  rule_type text NOT NULL CHECK (rule_type IN ('flat', 'by_year', 'by_year_month')),
  date_source text NOT NULL CHECK (date_source IN ('document_date', 'captured_date', 'upload_date')),
  is_active boolean NOT NULL DEFAULT true,
  created_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX one_active_placement_rule_per_primary_tag
  ON placement_rules(tag_id)
  WHERE is_active;

CREATE TABLE document_tag_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  tag_id uuid NOT NULL REFERENCES tags(id),
  assignment_role text NOT NULL CHECK (assignment_role IN ('primary', 'secondary')),
  status text NOT NULL CHECK (status IN ('proposed', 'applied', 'rejected')),
  confidence numeric,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX one_applied_primary_tag_per_document
  ON document_tag_assignments(document_id)
  WHERE assignment_role = 'primary' AND status = 'applied';

CREATE TABLE classification_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  model text NOT NULL,
  top_candidates jsonb NOT NULL DEFAULT '[]'::jsonb,
  top_score numeric,
  runner_up_score numeric,
  margin numeric,
  explanation text,
  similar_documents jsonb NOT NULL DEFAULT '[]'::jsonb,
  extraction_quality text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE document_relationships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  target_document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  relationship_type text NOT NULL CHECK (relationship_type IN ('duplicate_candidate', 'near_duplicate', 'related', 'same_theme', 'possible_newer_version')),
  score numeric,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE review_tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid REFERENCES documents(id) ON DELETE CASCADE,
  task_type text NOT NULL CHECK (task_type IN ('low_confidence', 'duplicate_review', 'misfiled_file', 'missing_destination', 'mapping_migration')),
  status text NOT NULL CHECK (status IN ('open', 'in_progress', 'resolved', 'dismissed')),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  resolution jsonb,
  reviewer text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE human_decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  review_task_id uuid REFERENCES review_tasks(id),
  final_primary_tag_id uuid REFERENCES tags(id),
  final_secondary_semantic_tag_ids uuid[] NOT NULL DEFAULT '{}',
  decision_type text NOT NULL CHECK (decision_type IN ('accepted_existing_tag', 'created_new_tag', 'ignored', 'duplicate_existing', 'keep_both', 'replace_with_newer')),
  note text,
  reviewer text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE drive_actions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  action_type text NOT NULL CHECK (action_type IN ('move', 'import_to_drive', 'rollback_move')),
  status text NOT NULL CHECK (status IN ('pending', 'applied', 'failed', 'rolled_back')),
  from_path text,
  to_path text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  result jsonb,
  error_message text,
  idempotency_key text UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz
);

CREATE TABLE migration_batches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_type text NOT NULL CHECK (batch_type IN ('tag_mapping_change', 'nas_import')),
  status text NOT NULL CHECK (status IN ('draft', 'approved', 'running', 'completed', 'failed')),
  summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor text,
  event_type text NOT NULL,
  entity_type text NOT NULL,
  entity_id uuid,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runtime_guard_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workflow_id text,
  document_id uuid REFERENCES documents(id) ON DELETE SET NULL,
  guard_type text NOT NULL,
  status text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
