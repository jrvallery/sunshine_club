CREATE TABLE IF NOT EXISTS provider_benchmark_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  benchmark_key text NOT NULL UNIQUE,
  output_dir text NOT NULL,
  status text NOT NULL,
  partial boolean NOT NULL DEFAULT false,
  summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  artifact_manifest jsonb NOT NULL DEFAULT '{}'::jsonb,
  background_error jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_benchmark_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  benchmark_run_id uuid NOT NULL REFERENCES provider_benchmark_runs(id) ON DELETE CASCADE,
  source_path text,
  relative_path text,
  sample_category text,
  sample_label text,
  provider text NOT NULL,
  status text NOT NULL,
  quality text,
  requires_review boolean,
  seconds numeric,
  result jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_benchmark_parser_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  benchmark_run_id uuid NOT NULL REFERENCES provider_benchmark_runs(id) ON DELETE CASCADE,
  source_path text,
  relative_path text,
  sample_category text,
  sample_label text,
  provider text NOT NULL,
  status text NOT NULL,
  quality text,
  requires_review boolean,
  seconds numeric,
  text_length integer,
  page_count integer,
  result jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_benchmark_recommendations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  benchmark_run_id uuid NOT NULL REFERENCES provider_benchmark_runs(id) ON DELETE CASCADE,
  provider text NOT NULL,
  recommendation text,
  status text,
  average_seconds numeric,
  result jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS provider_benchmark_results_run_idx ON provider_benchmark_results(benchmark_run_id);
CREATE INDEX IF NOT EXISTS provider_benchmark_results_provider_idx ON provider_benchmark_results(provider);
CREATE INDEX IF NOT EXISTS provider_benchmark_parser_results_run_idx ON provider_benchmark_parser_results(benchmark_run_id);
CREATE INDEX IF NOT EXISTS provider_benchmark_recommendations_run_idx ON provider_benchmark_recommendations(benchmark_run_id);
