CREATE INDEX IF NOT EXISTS pipeline_run_events_run_id_idx ON pipeline_run_events(run_id);
CREATE INDEX IF NOT EXISTS pipeline_run_events_run_id_created_at_idx ON pipeline_run_events(run_id, created_at);
