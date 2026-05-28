CREATE TABLE IF NOT EXISTS pipeline_chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES pipeline_runs(id) ON DELETE CASCADE,
  source_path text NOT NULL,
  relative_path text,
  sample_path text,
  chunk_id text NOT NULL,
  chunk_index integer NOT NULL,
  chunk_kind text NOT NULL,
  content text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS pipeline_chunk_embeddings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid REFERENCES pipeline_runs(id) ON DELETE CASCADE,
  chunk_id text NOT NULL,
  source_path text,
  relative_path text,
  embedding_provider text NOT NULL,
  embedding_model text NOT NULL,
  embedding_dimensions integer,
  embedding_status text NOT NULL,
  semantic_quality boolean NOT NULL DEFAULT false,
  embedding vector,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, chunk_id, embedding_provider, embedding_model)
);

CREATE INDEX IF NOT EXISTS pipeline_chunks_run_id_idx ON pipeline_chunks(run_id);
CREATE INDEX IF NOT EXISTS pipeline_chunks_source_path_idx ON pipeline_chunks(source_path);
CREATE INDEX IF NOT EXISTS pipeline_chunk_embeddings_run_id_idx ON pipeline_chunk_embeddings(run_id);
CREATE INDEX IF NOT EXISTS pipeline_chunk_embeddings_source_path_idx ON pipeline_chunk_embeddings(source_path);
