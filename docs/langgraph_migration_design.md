# LangGraph Migration Design

## Goal

Move the Sunshine Club document intelligence pipeline from the current
tracer-bullet Python runner into a LangGraph workflow.

The goal is not to change the product behavior first. The goal is to preserve
the working pipeline shape while making every stage explicit, resumable,
auditable, and safe to run for one file at a time or many files in batch.

The production workflow should support:

- single-file ingestion from a user-facing product flow
- batch processing from inventory or QA sample manifests
- local and external model providers
- OCR extraction and quality gates
- embeddings
- LLM tag inspection through Cortex/Gemma or another configured provider
- deterministic tag fallback
- route/review decisions
- durable audit artifacts

No source customer file should be modified, moved, deleted, or overwritten by
the graph.

## Current State

The current implementation lives in:

```text
packages/extraction/src/sunshine_extraction/sample_pipeline.py
```

It already has node-like function boundaries:

```text
select_sample_files
-> load_existing_content_class
-> load_existing_extraction_plan
-> extract_content
-> extraction_quality_gate
-> chunk_content
-> embed_chunks
-> assign_tag_candidates
-> LLM tag inspection
-> combine_tag_candidates
-> resolve_route_or_review
-> write_pipeline_result
```

This is why LangGraph was not started first: the risky part was not graph
syntax. The risky part was proving document classification, OCR, chunking,
embeddings, tag assignment, and review routing over real files. That shape now
exists and can be lifted into LangGraph with much lower risk.

## Product Promise

The LangGraph version must keep the same safety posture:

- every input file produces either a result, a review item, or a failed item
- failures are recorded, not hidden
- OCR quality problems are routed to review
- low-confidence tag decisions are routed to review
- model failures fall back to deterministic behavior when possible
- every output includes source path, relative path, sample path, and warnings
- original files remain untouched

The graph should make the pipeline easier to reason about, not more magical.

## Workflow Shape

### Single-File Graph

The primary production graph should process one file per graph invocation.

```text
START
  -> load_file_context
  -> classify_content_type
  -> plan_extraction
  -> extract_content
  -> quality_gate
  -> chunk_content
  -> embed_chunks
  -> assign_deterministic_tags
  -> inspect_tags_with_llm
  -> combine_tag_evidence
  -> resolve_route_or_review
  -> persist_outputs
END
```

### Batch Graph

Batch processing should be a thin wrapper around the single-file graph.

```text
load_batch_manifest
  -> for each file: invoke single-file graph
  -> aggregate_batch_summary
```

This avoids two separate implementations. Production upload, QA sample runs,
and corpus-wide processing should all use the same per-file graph.

## State Contract

Use a typed state object so every node has an explicit contract.

Initial state for a single file:

```python
class DocumentPipelineState(TypedDict, total=False):
    run_id: str
    file_id: str
    input_path: str
    source_path: str
    relative_path: str
    filename: str
    manifest_root: str
    output_dir: str

    content_class: dict
    extraction_plan: dict
    extraction_result: dict
    extraction_quality: dict
    ocr_pages: list[dict]
    ocr_document: dict
    chunks: list[dict]
    embeddings: list[dict]
    deterministic_tag_candidates: list[dict]
    llm_tag_inspection: dict
    tag_candidates: list[dict]
    route: dict
    final_result: dict

    warnings: list[str]
    errors: list[dict]
    audit_events: list[dict]
```

State rules:

- nodes append warnings; they do not erase prior warnings
- nodes append audit events for important decisions
- recoverable failures become state, not uncaught process crashes
- unrecoverable failures route to `persist_failure`
- large extracted text can be stored as an artifact and referenced by path if
  state size becomes too large

## Node Design

### load_file_context

Purpose:

- normalize file path
- resolve source path and relative path
- attach inventory/sample metadata if present
- verify the file exists

Success output:

- `filename`
- `source_path`
- `relative_path`
- basic file metadata

Failure behavior:

- route to `persist_failure` with `file_missing` or `file_unreadable`

### classify_content_type

Purpose:

- decide high-level content class for the file
- support existing corrected classes when running from QA or manifest data
- support standalone single-file classification in production

Classes should include the existing content classes:

- `document`
- `scanned_document`
- `image`
- `spreadsheet`
- `video`
- `deferred_technical`
- `binary_or_unknown`

Success output:

- `final_class`
- `confidence`
- `signals`
- `needs_review`

Failure behavior:

- route to review as `review_content_class_unknown`

### plan_extraction

Purpose:

- map content class and file signals to extraction strategy

Current strategies:

- `text_extraction`
- `ocr_page_level`
- `photo_metadata`
- `spreadsheet_table_extraction`
- `deferred_technical`

Success output:

- `strategy`
- `document_subtype`
- `ocr_required`
- `defer_reason`

Failure behavior:

- route to review as `review_extraction_plan_missing`

### extract_content

Purpose:

- execute the strategy chosen by `plan_extraction`
- preserve page-level OCR artifacts when OCR is used

Success output:

- `extraction_status`
- `text`
- `metadata`
- `page_count`
- `warnings`
- `ocr_pages`
- `ocr_document`

Failure behavior:

- record extractor failure
- continue to `quality_gate`
- do not silently mark failed extraction as usable

### quality_gate

Purpose:

- decide whether extracted content is trusted enough to chunk, embed, and route

Current qualities:

- `ok`
- `poor`
- `metadata_only`
- `empty`
- `deferred`
- `failed`

Routing:

- `ok` can continue normally
- `poor` can continue to chunk/embed but must route to review
- `metadata_only` can continue where useful but may require review
- `deferred` and `failed` route to review or technical follow-up

### chunk_content

Purpose:

- convert extracted text or metadata into chunks for embeddings and retrieval

Success output:

- chunk rows with stable `chunk_id`
- `chunk_kind`
- source path and relative path
- text
- metadata

Failure behavior:

- route to `review_chunking_failed`

### embed_chunks

Purpose:

- embed chunks with configured provider

Current provider:

- Gemini embeddings

Failure behavior:

- use placeholder embeddings only in development/test mode
- in production, record provider failure and route to retry or review

Success output:

- embedding rows with dimensions, provider, model, and status

### assign_deterministic_tags

Purpose:

- provide cheap, explainable tag candidates from filename, path, content, and
  metadata

This node is not a replacement for LLM inspection. It is a fallback and a
cross-check.

Success output:

- candidate tags
- confidence
- evidence strings
- assignment source `deterministic`

### inspect_tags_with_llm

Purpose:

- use a structured LLM prompt to assign one primary tag and zero to five
  secondary tags

Configured provider for the near-term production path:

- Cortex local OpenAI-compatible endpoint
- model `gemma4-26b`

Inputs to the LLM:

- relative path
- filename
- content class
- document subtype
- extraction strategy
- extraction status
- extraction metadata
- deterministic candidates
- text excerpt from extracted text or OCR

The node should not pass the raw binary file to the LLM for this milestone.

Success output:

- `primary_tag`
- `secondary_tags`
- `confidence`
- `evidence`
- `rationale`
- `needs_review`

Failure behavior:

- record `llm_tag_inspection_failed`
- continue with deterministic candidates if available
- lower confidence or route to review where evidence is weak

### combine_tag_evidence

Purpose:

- combine deterministic and LLM tag evidence into ranked candidates

Rules:

- when LLM and deterministic tag agree, increase confidence
- when they disagree, keep both candidates and route lower-confidence cases to
  review
- never let the LLM overwrite the audit trail

### resolve_route_or_review

Purpose:

- make the final routing decision

Possible route statuses:

- `route_candidate`
- `review_low_confidence_tag`
- `review_ocr_quality`
- `review_ocr_no_text`
- `review_no_tag_candidate`
- `review_failed_extraction`
- `review_content_class_unknown`
- `technical_followup`

### persist_outputs

Purpose:

- write durable artifacts
- write audit events
- make the result inspectable after the run

Initial artifact compatibility:

- continue writing JSONL artifacts compatible with the current sample pipeline
- later add database writes once the persistence model is finalized

Required per-file outputs:

- final pipeline result
- extraction result
- OCR pages and OCR document, if applicable
- chunks
- embeddings
- LLM inspection
- tag candidates
- audit events

## Conditional Edges

The graph should use conditional edges for quality and failure handling.

Examples:

```text
load_file_context
  -> classify_content_type
  -> persist_failure       when file is missing

quality_gate
  -> chunk_content         when can_chunk=true
  -> resolve_route_or_review when can_chunk=false

embed_chunks
  -> assign_deterministic_tags when embeddings succeed
  -> assign_deterministic_tags when embeddings fail but tags can still run

resolve_route_or_review
  -> persist_outputs
```

The graph should avoid stopping early unless persistence has recorded the
reason.

## Audit Requirements

Every node should append an audit event with:

```json
{
  "node": "extract_content",
  "status": "ok",
  "timestamp": "...",
  "duration_ms": 1234,
  "warnings": [],
  "summary": "OCR extracted 4 pages"
}
```

Audit events should make it possible to answer:

- which node changed the file state?
- what model or extractor was used?
- what confidence did it report?
- what warnings were present?
- why was the file routed to review?
- did the graph finish, fail, or defer?

## LangGraph Persistence

Use LangGraph checkpointing once the single-file graph is stable.

Initial development:

- in-memory graph for tests
- JSONL artifacts for output compatibility

Production-ready version:

- durable checkpoint store
- run id per file
- resumable state after extractor/model failures
- ability to retry from a failed node without reprocessing completed nodes

Checkpointing is important because OCR, embeddings, and LLM inspection can be
slow or rate-limited.

## Implementation Phases

### Phase 1: Graph Wrapper Around Existing Functions

Goal:

- build a LangGraph single-file graph that calls the existing functions

Scope:

- no behavior changes
- no database writes
- use current JSONL artifacts
- support one file from the QA sample set

Success criteria:

- one QA sample produces the same final result fields as the current runner
- graph state includes audit events for every node
- tests prove happy path and failed extraction path

### Phase 2: Batch Runner Uses Single-File Graph

Goal:

- replace the sample pipeline loop with a batch wrapper that invokes the
  single-file graph once per file

Scope:

- preserve existing output filenames
- preserve existing summary counters
- keep current CLI usable

Success criteria:

- running the 36-file QA sample set produces the same artifact types
- no source files are modified
- skipped/failed/review files are all counted
- graph run can continue after one file fails

### Phase 3: Production Single-File Entry Point

Goal:

- create a production API or worker entry point for one uploaded/selected file

Scope:

- input is a file path plus optional metadata
- graph returns final route/review result
- no dependency on QA sample folder structure

Success criteria:

- one arbitrary local file can run through classification to final route
- missing files produce auditable failure results
- review-required cases are explicit
- LLM provider can be switched by env config

### Phase 4: Durable Checkpointing and Retry

Goal:

- make long-running or failed jobs resumable

Scope:

- add LangGraph checkpointer
- persist node status
- support retry from failed model/OCR calls

Success criteria:

- interrupting a run does not lose completed node state
- retrying a failed LLM/OCR node does not rerun prior successful nodes
- run history can be inspected per file

### Phase 5: Corpus-Scale Processing

Goal:

- safely run the graph over large corrected manifests

Scope:

- concurrency limits
- provider rate limits
- retry policy
- progress reporting
- aggregate reports

Success criteria:

- batch run has no untracked files
- every input is in exactly one terminal state
- review queue is generated
- summary reports match artifact counts
- runtime and failure rate are measurable

## Success Criteria

The LangGraph migration is successful when all of the following are true.

### Functional Success

- A single file can run from input path to final route/review output.
- The QA sample set can run through the graph and produce current artifact
  equivalents.
- The graph supports existing classes and strategies.
- OCR output still includes page-level and document-level artifacts.
- LLM tag inspection uses Cortex when configured.
- Deterministic tag fallback still works when LLM inspection fails.

### Safety Success

- No source customer file is modified, moved, deleted, or overwritten.
- Every input file reaches one terminal state:
  - routed
  - review required
  - technical follow-up
  - failed with recorded reason
- No failed extractor or model call is treated as success.
- Low-quality OCR routes to review.
- Missing or unknown classification routes to review.

### Audit Success

- Every node writes an audit event.
- Every model call records provider, model, status, confidence, and warning.
- Every route decision records its reason.
- Every generated artifact can be traced back to source path and relative path.
- A customer-facing review report can be produced from graph outputs.

### Test Success

- Unit tests cover each node contract.
- Integration tests cover:
  - text document
  - scanned document with OCR
  - image metadata
  - spreadsheet metadata
  - deferred technical file
  - LLM tag success
  - LLM tag failure fallback
  - missing file
- Regression tests compare graph output to current sample pipeline output for a
  fixed QA subset.

### Operational Success

- The graph can run one file from the CLI.
- The graph can run a QA batch from the CLI.
- Provider configuration comes from `.env` or environment variables.
- Secrets are never printed in logs.
- Progress logs show current node and file.
- Failed files can be retried without manual cleanup.

## Non-Goals For The First Migration

- Do not rebuild all extractors.
- Do not replace the taxonomy.
- Do not switch OCR providers as part of the graph migration.
- Do not require a database before the graph works.
- Do not remove JSONL artifacts until the graph output is trusted.
- Do not make the LLM inspect raw binary files in the first version.

## Recommended Next Milestone

Current implementation status:

- Phase 1 is implemented in
  `packages/extraction/src/sunshine_extraction/langgraph_pipeline.py`.
- Phase 2 is implemented for QA sample batches through `--input-root`.
- Phase 4 durable checkpointing is implemented as an opt-in SQLite
  checkpointer through `--checkpoint-path`.
- Phase 3 production single-file entry point is implemented at
  `POST /admin/pipeline/run-file`.
- Phase 5 corpus-scale controls are implemented for batch runs through
  `--max-concurrency`, `--rate-limit-seconds`, `--limit`, checkpointing, retry,
  progress logging, and aggregate reports.
- Node retry is implemented through `--retry-attempts` and
  `--retry-delay-seconds`; retry attempts are recorded in audit events.
- The graph currently writes compatible JSONL artifacts, `graph-result.json`,
  `graph-audit-events.jsonl`, `graph-batch-summary.json`, and per-file
  `graph-runs/` folders.
- Remaining production hardening is mostly operational: choosing deployment
  defaults, external monitoring, and replacing JSONL-only persistence when the
  database model is ready.

Next hardening milestone:

```text
Operational production hardening
```

Single-file command:

```bash
.venv/bin/python -m sunshine_extraction.langgraph_pipeline \
  --input-file "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples/accepted-image-random-100/001 - 2006_May_Sunshine_Tea_2006_0014_a.jpg" \
  --source-path "Sunshine shared folders/Teas/2006_May_Sunshine_Tea_2006/2006_May_Sunshine_Tea_2006_0014_a.jpg" \
  --output-dir "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/langgraph-smoke" \
  --checkpoint-path "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/langgraph-smoke/checkpoints.sqlite" \
  --retry-attempts 2 \
  --enable-llm-tags \
  --llm-tag-provider cortex
```

Batch command:

```bash
.venv/bin/python -m sunshine_extraction.langgraph_pipeline \
  --input-root "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples" \
  --output-dir "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/langgraph-sample-batch" \
  --checkpoint-path "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/langgraph-sample-batch/checkpoints.sqlite" \
  --retry-attempts 2 \
  --max-concurrency 1 \
  --rate-limit-seconds 0 \
  --enable-llm-tags \
  --llm-tag-provider cortex
```

Expected single-file output:

- `graph-result.json`
- `graph-audit-events.jsonl`
- `sample-review-queue.jsonl`
- compatible per-file pipeline artifacts

Expected batch output:

- compatible sample pipeline JSONL artifacts
- `sample-pipeline-summary.json`
- `sample-ocr-summary.json`
- `sample-review-queue.jsonl`
- `graph-batch-summary.json`
- per-file `graph-runs/` folders
- optional SQLite checkpoint database when `--checkpoint-path` is provided
