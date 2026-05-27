# Review Dashboard Workflow

## Goal

Use the LangGraph pipeline output as the source for a clean review dashboard
instead of manually scanning JSONL files.

## Run A Batch

```bash
.venv/bin/python -m sunshine_extraction.langgraph_pipeline \
  --input-root "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples" \
  --output-dir "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/langgraph-sample-batch-cortex" \
  --checkpoint-path "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/langgraph-sample-batch-cortex/checkpoints.sqlite" \
  --retry-attempts 2 \
  --max-concurrency 1 \
  --enable-llm-tags \
  --llm-tag-provider cortex
```

## Import Results Into Review DB

Default local DB:

```text
.local/sunshine-review.sqlite
```

Import command:

```bash
curl -X POST http://localhost:8000/admin/review/import-langgraph-output \
  -H 'Content-Type: application/json' \
  -d '{"output_dir":"/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/langgraph-sample-batch-cortex"}'
```

## Start The Apps

API:

```bash
.venv/bin/uvicorn sunshine_api.main:app --host 0.0.0.0 --port 8000
```

Dashboard:

```bash
SUNSHINE_API_URL=http://localhost:8000 npm --workspace apps/dashboard run dev
```

Dashboard URL:

```text
http://localhost:3000
```

## Review API

Summary:

```bash
curl http://localhost:8000/admin/review/summary
```

Open items:

```bash
curl 'http://localhost:8000/admin/review/items?status=open&limit=100'
```

Record a decision:

```bash
curl -X POST http://localhost:8000/admin/review/items/1/decision \
  -H 'Content-Type: application/json' \
  -d '{"decision":"accept","correct_class":"scanned_document","correct_tag":"meeting_records","notes":"Looks correct."}'
```

## Current Scope

The review database is SQLite for local review speed. It is intentionally small
and can be replaced by Postgres once the production persistence schema is ready.

The dashboard currently shows:

- total imported results
- open and resolved review counts
- route-status breakdown
- extraction-quality breakdown
- open review queue
- file path, reason, class, tag, confidence, quality, warnings, and evidence
