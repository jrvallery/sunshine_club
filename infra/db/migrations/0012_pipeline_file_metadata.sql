CREATE TABLE IF NOT EXISTS pipeline_file_metadata (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES pipeline_runs(id) ON DELETE CASCADE,
  source_path text,
  relative_path text,
  sample_path text,
  metadata_type text NOT NULL,
  file_id text,
  content_sha256 text,
  size_bytes bigint,
  extension text,
  mime_type text,
  media_type text,
  status text,
  provider text,
  page_count integer,
  text_length integer,
  sample_group text,
  sample_number integer,
  final_class text,
  extraction_strategy text,
  import_status text,
  warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
  result jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pipeline_file_metadata_run_id_idx ON pipeline_file_metadata(run_id);
CREATE INDEX IF NOT EXISTS pipeline_file_metadata_source_path_idx ON pipeline_file_metadata(source_path);
CREATE INDEX IF NOT EXISTS pipeline_file_metadata_type_idx ON pipeline_file_metadata(metadata_type);
CREATE INDEX IF NOT EXISTS pipeline_file_metadata_file_id_idx ON pipeline_file_metadata(file_id);
