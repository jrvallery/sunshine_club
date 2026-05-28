CREATE TABLE IF NOT EXISTS pipeline_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_key text NOT NULL UNIQUE,
  preset_key text,
  input_root text,
  output_dir text NOT NULL,
  status text NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  local_only boolean NOT NULL DEFAULT true,
  embedding_provider text,
  embedding_model text,
  llm_provider text,
  llm_model text,
  extraction_provider text,
  vector_store_provider text,
  vector_store_collection text,
  started_at timestamptz,
  finished_at timestamptz,
  summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pipeline_run_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
  source_path text,
  relative_path text,
  node text,
  status text NOT NULL,
  message text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pipeline_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES pipeline_runs(id) ON DELETE CASCADE,
  source_path text NOT NULL,
  relative_path text,
  sample_path text,
  route_status text NOT NULL,
  review_reason text,
  final_class text,
  extraction_strategy text,
  extraction_status text,
  quality text,
  top_tag_candidate text,
  secondary_tags jsonb NOT NULL DEFAULT '[]'::jsonb,
  tag_confidence numeric,
  result jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, source_path)
);

CREATE TABLE IF NOT EXISTS provider_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES pipeline_runs(id) ON DELETE CASCADE,
  source_path text,
  relative_path text,
  provider text NOT NULL,
  capability text NOT NULL,
  status text NOT NULL,
  strategy text,
  runtime_ms integer,
  warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_usage (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES pipeline_runs(id) ON DELETE CASCADE,
  source_path text,
  relative_path text,
  node text NOT NULL,
  purpose text NOT NULL,
  provider text NOT NULL,
  model text,
  status text NOT NULL,
  call_count integer NOT NULL DEFAULT 0,
  input_tokens integer,
  output_tokens integer,
  total_tokens integer,
  runtime_ms integer,
  local_only boolean NOT NULL DEFAULT true,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_segments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES pipeline_runs(id) ON DELETE CASCADE,
  source_path text NOT NULL,
  relative_path text,
  segment_id text NOT NULL,
  parent_file_id text,
  page_start integer,
  page_end integer,
  segment_index integer NOT NULL,
  segment_type text NOT NULL,
  segment_title text,
  segment_confidence numeric NOT NULL,
  requires_segment_review boolean NOT NULL DEFAULT false,
  boundary_evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, segment_id)
);

CREATE TABLE IF NOT EXISTS review_items_v2 (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES pipeline_runs(id) ON DELETE SET NULL,
  source_path text NOT NULL,
  relative_path text,
  segment_id text,
  status text NOT NULL CHECK (status IN ('open', 'accepted', 'changed', 'deferred', 'rejected')),
  review_reason text,
  proposed_class text,
  proposed_tag text,
  proposed_secondary_tags jsonb NOT NULL DEFAULT '[]'::jsonb,
  corrected_class text,
  corrected_tag text,
  corrected_secondary_tags jsonb NOT NULL DEFAULT '[]'::jsonb,
  notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pipeline_results_run_id_idx ON pipeline_results(run_id);
CREATE INDEX IF NOT EXISTS provider_attempts_run_id_idx ON provider_attempts(run_id);
CREATE INDEX IF NOT EXISTS model_usage_run_id_idx ON model_usage(run_id);
CREATE INDEX IF NOT EXISTS document_segments_run_id_idx ON document_segments(run_id);
CREATE INDEX IF NOT EXISTS review_items_v2_run_id_idx ON review_items_v2(run_id);
