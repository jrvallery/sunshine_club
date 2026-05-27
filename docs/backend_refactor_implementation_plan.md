# Backend Refactor Implementation Plan

Last updated: 2026-05-27

## Goal

Make the backend and LangGraph pipeline navigable enough that a developer or agent
can quickly answer:

- where an API route lives
- where request/response models live
- where run execution and report generation live
- where review/file persistence lives
- where LangGraph topology lives
- where LangGraph nodes live
- where batch artifact aggregation lives

This refactor must preserve behavior. It is a structure refactor, not a product
rewrite.

## Checkpoint

Checkpoint commit before refactor:

```text
9351599 Checkpoint dashboard and document pipeline
```

Refactor branch:

```text
refactor/backend-structure
```

## Current Pain

### FastAPI

Current file:

```text
apps/api/src/sunshine_api/main.py
```

Current issue:

- route models, route handlers, command construction, subprocess execution,
  run report generation, artifact readers, model usage summaries, semantic
  index endpoints, and health/foundation endpoints all live in one file.
- the file is around 1,600 lines.
- there is no obvious module boundary between API transport code and backend
  workflow code.

### Review Store

Current file:

```text
apps/api/src/sunshine_api/review_store.py
```

Current issue:

- review queue operations, file browser index/search, pipeline run persistence,
  model usage, schema creation, and row serializers live in one class/file.
- it is usable but too large for quick navigation.

### LangGraph

Current file:

```text
packages/extraction/src/sunshine_extraction/langgraph_pipeline.py
```

Current issue:

- public graph entry points, graph topology, batch runner, node implementations,
  artifact persistence, and CLI live in one file.
- the graph topology is real, but not isolated from implementation details.

## Target API Structure

### `apps/api/src/sunshine_api/main.py`

Purpose:

- create the FastAPI app
- include routers
- expose no business logic

Functions/classes:

- `app`
- no request models
- no route helper functions

### `apps/api/src/sunshine_api/dependencies.py`

Purpose:

- shared app dependencies

Functions:

- `review_store() -> ReviewStore`

### `apps/api/src/sunshine_api/schemas.py`

Purpose:

- Pydantic request/response models for API routes

Classes:

- `DocumentPipelineRunRequest`
- `DocumentPipelineRunResponse`
- `ReviewImportRequest`
- `ReviewDecisionRequest`
- `FileReviewRequest`
- `FileRunRequest`
- `GoldenLabelUpdateRequest`
- `ReviewAssignRequest`
- `RunStartRequest`
- `SemanticIndexBuildRequest`
- `SemanticEvalRequest`

### `apps/api/src/sunshine_api/routers/health.py`

Purpose:

- health endpoint and foundation thin-slice endpoint

Functions:

- `healthz`
- `run_staged_file`

### `apps/api/src/sunshine_api/routers/pipeline.py`

Purpose:

- one-file pipeline execution endpoint
- manual import endpoint for LangGraph output

Functions:

- `run_pipeline_file`
- `import_langgraph_output`

### `apps/api/src/sunshine_api/routers/review.py`

Purpose:

- review queue, review decisions, golden labels, placement report, review export

Functions:

- `review_summary`
- `review_placement_report`
- `review_export`
- `golden_labels`
- `golden_label_summary`
- `update_golden_label`
- `delete_golden_label`
- `golden_label_file`
- `review_items`
- `review_facets`
- `review_item_detail`
- `record_review_decision`
- `assign_review_item`
- `review_item_file`
- `review_item_text`
- `review_item_neighbors`

### `apps/api/src/sunshine_api/routers/files.py`

Purpose:

- file browser, file inspection, preview/text, add-to-review, single-file runs

Functions:

- `files`
- `file_search`
- `file_facets`
- `file_detail`
- `file_inspection`
- `file_preview`
- `file_text`
- `add_file_to_review`
- `run_file_from_browser`

### `apps/api/src/sunshine_api/routers/runs.py`

Purpose:

- run presets, run lifecycle, run progress, run artifacts/results/report,
  cancellation, import, rerun failed

Functions:

- `run_presets`
- `start_run`
- `runs`
- `run_detail`
- `run_events`
- `run_progress`
- `run_results`
- `run_artifacts`
- `run_model_usage`
- `run_report`
- `run_compare_previous`
- `cancel_run`
- `import_run_results`
- `rerun_failed`

### `apps/api/src/sunshine_api/routers/semantic.py`

Purpose:

- semantic index and semantic evaluation endpoints

Functions:

- `semantic_index_status`
- `semantic_index_build`
- `semantic_eval_latest`
- `semantic_eval_run`

### `apps/api/src/sunshine_api/services/run_commands.py`

Purpose:

- build commands for batch and single-file LangGraph runs

Functions:

- `batch_command`
- `single_file_command`
- `batch_input_sample_count`

### `apps/api/src/sunshine_api/services/run_execution.py`

Purpose:

- subprocess lifecycle and live run log/progress streaming

Module data:

- `RUN_PROCESSES`
- `RUN_PROCESS_LOCK`
- `RUN_PROGRESS_PATTERN`

Functions:

- `execute_run`
- `stream_run_output`
- `is_error_log`
- `progress_payload_from_message`

### `apps/api/src/sunshine_api/services/run_reports.py`

Purpose:

- run progress/result/report/diff helpers independent of FastAPI transport

Functions:

- `read_live_run_summary`
- `count_jsonl_rows`
- `progress_total`
- `progress_ratio`
- `read_run_summary`
- `load_run_results_by_source`
- `read_jsonl_file`
- `run_artifacts`
- `training_cycle_metrics`
- `review_item_mentions`
- `ratio`
- `result_file_rows`
- `count_values`
- `count_list_values`

### `apps/api/src/sunshine_api/services/model_usage.py`

Purpose:

- model usage artifact parsing and cost/runtime summaries

Functions:

- `read_model_usage_artifact`
- `model_usage_report`
- `is_external_model_call`
- `model_usage_breakdowns`
- `sum_numeric`

### `apps/api/src/sunshine_api/services/semantic.py`

Purpose:

- semantic index status helper

Functions:

- `semantic_index_status`

## Target Review Store Structure

Keep `ReviewStore` intact for this pass to avoid mixing persistence refactor with
API/LangGraph refactor. Add a module docstring and clear section comments.

Future pass:

- `review_store/schema.py`
- `review_store/reviews.py`
- `review_store/files.py`
- `review_store/runs.py`
- `review_store/serializers.py`

Reason for deferring:

- `ReviewStore` is a persistence module with many related SQL queries. Moving
  methods before isolating tests around each persistence interface would add risk.

## Target LangGraph Structure

### `packages/extraction/src/sunshine_extraction/langgraph_pipeline.py`

Purpose:

- compatibility wrapper and CLI entry point
- re-export public functions

Functions/classes exposed:

- `DocumentPipelineState`
- `DocumentPipelineDeps`
- `run_document_graph`
- `run_document_batch`
- `build_document_graph`
- `main`

### `packages/extraction/src/sunshine_extraction/graph/state.py`

Purpose:

- graph state/dependency types

Classes:

- `DocumentPipelineState`
- `DocumentPipelineDeps`

### `packages/extraction/src/sunshine_extraction/graph/runtime.py`

Purpose:

- single-file graph runner and dependency resolution

Functions:

- `run_document_graph`
- `resolve_deps`
- `semantic_index_path_from_env`

### `packages/extraction/src/sunshine_extraction/graph/build.py`

Purpose:

- graph topology only

Functions:

- `build_document_graph`
- `after_load_file_context`
- `after_quality_gate`

### `packages/extraction/src/sunshine_extraction/graph/nodes.py`

Purpose:

- graph node implementations

Functions:

- `run_node`
- `merge_state`
- `load_file_context`
- `classify_content_type`
- `plan_extraction`
- `extract_content_node`
- `validate_text_extraction_node`
- `quality_gate`
- `chunk_content_node`
- `embed_chunks_node`
- `retrieve_labeled_examples_node`
- `assign_deterministic_tags`
- `inspect_tags_with_llm`
- `combine_tag_evidence`
- `resolve_route_or_review_node`
- `persist_outputs`
- `final_result_from_state`
- `empty_extraction`
- `node_summary`
- `json_safe`
- `write_jsonl`

### `packages/extraction/src/sunshine_extraction/graph/batch.py`

Purpose:

- batch runner and aggregate artifact writer

Functions:

- `run_document_batch`
- `run_batch_item`
- `rows_by_key`
- `append_batch_rows`
- `empty_summary_counters`
- `update_batch_summary_counters`
- `review_queue_row`
- `chunk_count_bucket`

### `packages/extraction/src/sunshine_extraction/graph/cli.py`

Purpose:

- CLI parsing and `python -m sunshine_extraction.langgraph_pipeline` behavior

Functions:

- `parse_args`
- `main`
- `progress`

## Documentation Requirement

Every new Python file must start with a module docstring explaining:

- what the file owns
- what it intentionally does not own
- the main public functions/classes in the file

## Implementation Slices

1. Split FastAPI `main.py` into schemas, dependencies, routers, and services.
2. Run tests.
3. Split LangGraph pipeline into `graph/` modules while keeping
   `langgraph_pipeline.py` as the compatibility module.
4. Run tests.
5. Add/adjust docs.
6. Run full Python tests and dashboard build.

## Verification Gates

Required after refactor:

```bash
.venv/bin/python -m pytest -q
npm --workspace apps/dashboard run build
```

Runtime smoke:

```bash
curl http://127.0.0.1:8001/healthz
curl http://127.0.0.1:8001/admin/runs/presets
curl http://127.0.0.1:8001/admin/review/summary
curl http://127.0.0.1:8001/admin/files/search?limit=1
```
