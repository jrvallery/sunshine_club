CREATE TABLE IF NOT EXISTS pipeline_artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES pipeline_runs(id) ON DELETE CASCADE,
  name text NOT NULL,
  path text,
  kind text,
  exists boolean NOT NULL DEFAULT false,
  size_bytes bigint,
  row_count integer,
  sha256 text,
  note text,
  result jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, name)
);

CREATE INDEX IF NOT EXISTS pipeline_artifacts_run_id_idx ON pipeline_artifacts(run_id);
CREATE INDEX IF NOT EXISTS pipeline_artifacts_name_idx ON pipeline_artifacts(name);
CREATE INDEX IF NOT EXISTS pipeline_artifacts_kind_idx ON pipeline_artifacts(kind);
