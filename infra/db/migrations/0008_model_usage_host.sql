ALTER TABLE model_usage
  ADD COLUMN IF NOT EXISTS host text;

UPDATE model_usage
SET host = metadata ->> 'host'
WHERE host IS NULL
  AND metadata ? 'host';

CREATE INDEX IF NOT EXISTS model_usage_host_idx ON model_usage(host);
