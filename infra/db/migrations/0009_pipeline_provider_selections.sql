CREATE TABLE IF NOT EXISTS pipeline_provider_selections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES pipeline_runs(id) ON DELETE CASCADE,
  source_path text,
  relative_path text,
  selected_provider text NOT NULL,
  preferred_provider text,
  configured_provider text,
  provider_chain jsonb NOT NULL DEFAULT '[]'::jsonb,
  skipped_providers jsonb NOT NULL DEFAULT '[]'::jsonb,
  provider_selection_reason text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pipeline_provider_selections_run_id_idx ON pipeline_provider_selections(run_id);
CREATE INDEX IF NOT EXISTS pipeline_provider_selections_source_path_idx ON pipeline_provider_selections(source_path);
