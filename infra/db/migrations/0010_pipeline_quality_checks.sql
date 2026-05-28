CREATE TABLE IF NOT EXISTS pipeline_quality_checks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES pipeline_runs(id) ON DELETE CASCADE,
  source_path text,
  relative_path text,
  check_type text NOT NULL,
  status text,
  quality text,
  requires_review boolean,
  can_chunk boolean,
  can_embed boolean,
  provider text,
  strategy text,
  reason text,
  warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
  result jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pipeline_quality_checks_run_id_idx ON pipeline_quality_checks(run_id);
CREATE INDEX IF NOT EXISTS pipeline_quality_checks_source_path_idx ON pipeline_quality_checks(source_path);
CREATE INDEX IF NOT EXISTS pipeline_quality_checks_type_idx ON pipeline_quality_checks(check_type);
