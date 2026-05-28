CREATE TABLE IF NOT EXISTS pipeline_processing_artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES pipeline_runs(id) ON DELETE CASCADE,
  source_path text,
  relative_path text,
  sample_path text,
  artifact_type text NOT NULL,
  provider text,
  model text,
  status text,
  quality text,
  strategy text,
  page_number integer,
  text_length integer,
  requested_count integer,
  embedded_count integer,
  dimensions integer,
  cache_hits integer,
  cache_misses integer,
  warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
  result jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pipeline_processing_artifacts_run_id_idx ON pipeline_processing_artifacts(run_id);
CREATE INDEX IF NOT EXISTS pipeline_processing_artifacts_source_path_idx ON pipeline_processing_artifacts(source_path);
CREATE INDEX IF NOT EXISTS pipeline_processing_artifacts_type_idx ON pipeline_processing_artifacts(artifact_type);
CREATE INDEX IF NOT EXISTS pipeline_processing_artifacts_status_idx ON pipeline_processing_artifacts(status);
