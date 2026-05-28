CREATE TABLE IF NOT EXISTS pipeline_tagging_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES pipeline_runs(id) ON DELETE CASCADE,
  source_path text,
  relative_path text,
  evidence_type text NOT NULL,
  status text,
  provider text,
  model text,
  primary_tag text,
  confidence numeric,
  assignment_source text,
  route_status text,
  review_reason text,
  placement_status text,
  destination_path text,
  warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
  evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
  result jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pipeline_tagging_evidence_run_id_idx ON pipeline_tagging_evidence(run_id);
CREATE INDEX IF NOT EXISTS pipeline_tagging_evidence_source_path_idx ON pipeline_tagging_evidence(source_path);
CREATE INDEX IF NOT EXISTS pipeline_tagging_evidence_type_idx ON pipeline_tagging_evidence(evidence_type);
CREATE INDEX IF NOT EXISTS pipeline_tagging_evidence_primary_tag_idx ON pipeline_tagging_evidence(primary_tag);
