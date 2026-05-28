CREATE TABLE IF NOT EXISTS pipeline_parser_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES pipeline_runs(id) ON DELETE CASCADE,
  source_path text,
  relative_path text,
  sample_path text,
  sample_group text,
  sample_number integer,
  provider text NOT NULL,
  status text NOT NULL,
  quality text,
  requires_review boolean,
  strategy text,
  document_subtype text,
  review_reason text,
  text_length integer,
  page_count integer,
  page_structure_available boolean,
  page_text_coverage_rate numeric,
  layout_signal_count integer,
  result jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pipeline_parser_results_run_id_idx ON pipeline_parser_results(run_id);
CREATE INDEX IF NOT EXISTS pipeline_parser_results_provider_idx ON pipeline_parser_results(provider);
CREATE INDEX IF NOT EXISTS pipeline_parser_results_status_idx ON pipeline_parser_results(status);
CREATE INDEX IF NOT EXISTS pipeline_parser_results_quality_idx ON pipeline_parser_results(quality);
