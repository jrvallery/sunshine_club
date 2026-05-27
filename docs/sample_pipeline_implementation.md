# QA Sample Pipeline Implementation

## Goal

Build a vertical tracer-bullet pipeline over a small QA sample set.

The goal is to prove the end-to-end shape of the product before investing more
deeply in any single extractor. This pipeline should take files from known
content-class decisions through extraction planning, extraction, chunking,
embedding, tag assignment, and routing/review output.

This is not the final production extractor. It is the first complete practice
run of the full system loop.

## Why This Comes Next

The project now has:

- inventory rows
- content-class probes
- human/heuristic review overrides
- corrected content classes
- extraction plans

The next risk is the handoff between pipeline stages:

```text
content class
-> extraction plan
-> extraction result
-> chunks
-> embeddings
-> tag candidates
-> route/review decision
```

Building OCR alone would prove only one node. The tracer-bullet pipeline proves
the whole graph shape and identifies the next highest-value extractor work.

## Input Scope

Primary input:

- `/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples`

Start with a small deterministic subset:

- 10 accepted images
- 10 accepted scanned documents
- 5 changed `image -> scanned_document`
- 5 changed `scanned_document -> document`
- 5 changed `document -> scanned_document`
- the 1 changed `binary_or_unknown -> spreadsheet`

Target initial run size: 36 files.

If this is too small to exercise the flow, expand to:

- 20 accepted images
- 20 accepted scanned documents
- 10 from each changed category

Maximum initial run size: 71 files.

## Outputs

Write outputs under:

```text
/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/sample-pipeline/
```

Required artifacts:

- `sample-inputs.jsonl`
- `sample-extraction-results.jsonl`
- `sample-chunks.jsonl`
- `sample-embeddings.jsonl`
- `sample-llm-tag-inspections.jsonl`
- `sample-tag-candidates.jsonl`
- `sample-pipeline-results.jsonl`
- `sample-pipeline-summary.json`

No source file should be moved, modified, or deleted.

## LangGraph Shape

The eventual graph should look like:

```text
load_sample_file
  -> load_existing_content_class
  -> load_existing_extraction_plan
  -> extract_content
  -> extraction_quality_gate
  -> chunk_content
  -> embed_chunks
  -> assign_tag_candidates
  -> resolve_route_or_review
  -> write_pipeline_result
```

For this milestone, the implementation may be a normal Python runner that keeps
the same node boundaries as functions. The boundaries should be easy to lift
into LangGraph later.

## Node Contracts

### load_sample_file

Input:

- sample copied file path
- sample folder/index metadata

Output:

- source path
- relative path
- copied sample path
- sample group

### load_existing_content_class

Input:

- source path or relative path
- `corrected-content-classes.jsonl`

Output:

- final class
- final status
- review decision, if any
- review notes, if any

### load_existing_extraction_plan

Input:

- source path or relative path
- `extraction-plan.jsonl`

Output:

- extraction strategy
- document subtype
- OCR required flag
- metadata extraction flags
- defer reason, if any

### extract_content

Input:

- sample file
- extraction plan

Output:

- extraction status
- extracted text
- extracted metadata
- page count, if available
- warnings

Initial executor behavior:

- `text_extraction`
  - PDF: use `pypdf` text extraction.
  - Plain text/Markdown/HTML: read text.
  - Other document formats: mark `deferred_extractor`.

- `photo_metadata`
  - Use Pillow to read format, dimensions, frame count, mode, EXIF date if
    available.
  - Text output may be empty.

- `spreadsheet_table_extraction`
  - Initial version may emit workbook/file metadata only.
  - If a spreadsheet parser is available, preserve sheet names and dimensions.

- `ocr_page_level`
  - If OCR tooling is installed, run OCR page by page.
  - If OCR tooling is not installed, emit a structured placeholder:
    `status = deferred_extractor`
    `warnings = ["ocr_executor_not_installed"]`
  - The pipeline should still continue to chunk metadata so the graph shape is
    exercised.

- `deferred_technical`
  - Do not extract.
  - Emit defer reason and stop at quality gate.

### extraction_quality_gate

Input:

- extraction result

Output:

- `quality = ok | metadata_only | empty | deferred | failed`
- `can_chunk`
- `can_embed`
- `requires_review`

Rules:

- Non-empty text -> `ok`
- Metadata-only photo extraction -> `metadata_only`
- OCR placeholder -> `deferred`
- Missing/unreadable file -> `failed`
- Deferred technical -> `deferred`

### chunk_content

Input:

- extraction result

Output:

- zero or more chunks

Initial rules:

- Text extraction: split into simple chunks by character length.
- Scanned/OCR placeholder: create one metadata chunk per file.
- Photo metadata: create one metadata chunk per file.
- Deferred technical: no chunks.

Chunk rows should include:

- source path
- chunk id
- chunk kind: `text | metadata`
- text
- metadata

### embed_chunks

Input:

- chunks

Output:

- embedding rows

Initial behavior:

- If a real embedding provider is configured, use it.
- Otherwise, emit deterministic placeholder vectors with:
  - `embedding_model = local-placeholder`
  - `embedding_status = placeholder`

The placeholder must be clearly marked so nobody mistakes it for semantic
quality.

### assign_tag_candidates

Input:

- extraction text
- metadata
- relative path
- extraction plan
- taxonomy seed
- optional structured LLM inspection result

Output:

- candidate primary tags
- candidate secondary tags
- confidence
- evidence

Initial deterministic rules:

- scrapbook evidence -> `scrapbooks`
- newspaper/article/profile evidence -> `press_publications`
- tea/guest list evidence -> `annual_spring_tea`
- meeting/minutes evidence -> `meeting_records`
- dental evidence -> `dental_program`
- treasurer/paypal/receipt evidence -> `finance_treasurer_records`
- incorporation/legal/insurance evidence -> `legal_insurance_compliance`
- photo/history evidence -> `historical_photos`
- fallback history/archive evidence -> `history_archive_general`

The rule engine should produce explanations, not just labels.

### inspect_tags_with_llm

Input:

- extraction text excerpt
- metadata
- relative path
- extraction plan
- deterministic tag candidates
- taxonomy primary tags and secondary facets

Output:

- `llm_status = inspected | skipped | failed | invalid`
- one primary tag
- zero to five secondary tags
- confidence
- evidence
- rationale
- needs-review flag

Initial behavior:

- Disabled unless `--enable-llm-tags` is passed or an LLM tag provider is
  configured.
- Uses Gemini structured JSON output when enabled.
- Writes one audit row per sample to `sample-llm-tag-inspections.jsonl`.
- If the LLM primary tag agrees with a deterministic primary tag, the combined
  confidence is boosted.
- If the LLM disagrees, the LLM candidate is added with a capped confidence so
  disagreement does not silently override deterministic evidence.
- If the LLM fails, deterministic candidates remain authoritative and the row
  records an explicit warning/status.

### resolve_route_or_review

Input:

- tag candidates
- extraction quality
- extraction plan

Output:

- route candidate or review state

Initial rules:

- high-confidence deterministic tag + non-deferred extraction -> route candidate
- metadata-only image -> route candidate if path/tag evidence is strong
- OCR deferred -> review/extraction-deferred state
- technical deferred -> technical follow-up state
- no tag candidate -> review state

## Result Record

Each row in `sample-pipeline-results.jsonl` should include:

```json
{
  "sample_path": "...",
  "source_path": "...",
  "relative_path": "...",
  "sample_group": "...",
  "final_class": "scanned_document",
  "document_subtype": "scrapbook",
  "extraction_strategy": "ocr_page_level",
  "extraction_status": "deferred_extractor",
  "quality": "deferred",
  "chunk_count": 1,
  "embedding_status": "placeholder",
  "top_tag_candidate": "scrapbooks",
  "tag_confidence": 0.9,
  "secondary_tags": [
    "scrapbook_page",
    "drive_search"
  ],
  "tag_assignment_source": "deterministic+llm",
  "llm_status": "inspected",
  "llm_primary_tag": "scrapbooks",
  "llm_confidence": 0.92,
  "tag_evidence": [
    "document_subtype=scrapbook",
    "path contains Scrapbook"
  ],
  "route_status": "review_or_extraction_deferred",
  "warnings": [
    "ocr_executor_not_installed"
  ]
}
```

## Success Criteria

### Functional

- Reads the QA sample folder.
- Selects the deterministic initial sample set.
- Loads corrected content-class rows.
- Loads extraction plan rows.
- Runs an extraction executor for each selected sample.
- Runs a quality gate for each selected sample.
- Emits chunks where possible.
- Emits embeddings or explicit placeholder embeddings.
- Assigns deterministic tag candidates for every non-technical-deferred sample.
- Optionally runs structured LLM tag inspection to map one primary tag and
  secondary tags, then uses that result to influence candidate confidence.
- Emits a route/review outcome for every sample.
- Writes all required output artifacts.

### Coverage

The initial run must include at least one file for each available strategy in
the sample set:

- `ocr_page_level`
- `photo_metadata`
- `text_extraction`, if present in the sample set
- `spreadsheet_table_extraction`
- `deferred_technical`, if present in the sample set

If the QA sample set does not include a strategy, the summary must say so
explicitly.

### Safety

- Source files are never moved, modified, or deleted.
- Copied QA sample files may be read but not modified.
- Placeholder embeddings are clearly marked.
- OCR-not-installed cases are explicit deferred extraction outcomes, not silent
  successes.
- Technical-deferred files are excluded from search/chat route candidates.

### Quality

- `sample-pipeline-summary.json` includes counts by:
  - sample group
  - final class
  - extraction strategy
  - extraction status
  - quality
  - chunk count bucket
  - embedding status
  - LLM status
  - top tag candidate
  - secondary tag
  - route status
  - warning

- Tests cover:
  - text extraction path
  - photo metadata path
  - OCR placeholder/deferred path
  - spreadsheet metadata path
  - deferred technical path
  - deterministic tag assignment
  - structured LLM tag assignment and confidence influence
  - one input sample produces one pipeline result

### Acceptance Gate

The milestone is complete when:

- `sample-pipeline-results.jsonl` exists.
- `sample-pipeline-summary.json` exists.
- `sample-llm-tag-inspections.jsonl` exists.
- every selected sample has exactly one result row.
- every result has an extraction status.
- every non-technical-deferred result has at least one chunk or an explicit
  deferred extraction warning.
- every non-technical-deferred result has a tag candidate or explicit review
  reason.
- `pytest` passes.
- dashboard build passes.

## Non-Goals

- Do not implement production-grade OCR in this milestone.
- Do not write embeddings to Postgres yet.
- Do not move files in Google Drive.
- Do not claim placeholder embeddings are semantically useful.
- Do not require perfect semantic tagging.

## Expected Next Step

After this tracer-bullet pipeline works, implement the real
`ocr_page_level` executor for `scanned_document`, because that strategy covers
the largest share of the corpus.

## Current Implementation Status

Implemented runner:

```bash
python -m sunshine_extraction.sample_pipeline \
  --input-root "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples" \
  --output-dir "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/sample-pipeline"
```

Latest placeholder-embedding QA run:

- selected samples: 36
- input rows: 36
- extraction result rows: 36
- chunk rows: 190
- embedding rows: 190
- LLM tag inspection rows: 36
- tag candidate rows: 118
- final result rows: 36

Covered strategies:

- `ocr_page_level`: 20
- `photo_metadata`: 10
- `text_extraction`: 5
- `spreadsheet_table_extraction`: 1

Missing from current QA sample set:

- `deferred_technical`

Route/review outcomes:

- `route_candidate`: 16
- `review_or_extraction_deferred`: 20

The 20 deferred rows are expected OCR placeholders with
`ocr_executor_not_installed`. This is the explicit non-production OCR behavior
called for by this milestone.

LLM status for the latest local run:

- `skipped`: 36

The local agent shell did not have `GEMINI_API_KEY`, so the real QA rerun did
not spend Gemini LLM calls. The structured LLM tag path is covered by unit tests
with a mocked inspector. To run real Gemini tag inspection, execute:

```bash
export SUNSHINE_LLM_TAG_MODEL=gemini-2.5-flash
python -m sunshine_extraction.sample_pipeline \
  --enable-llm-tags \
  --input-root "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples" \
  --output-dir "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/sample-pipeline-llm"
```

Verification:

- `pytest`: 54 passed
- dashboard build: passed
- artifact audit: 36 selected samples, 36 result rows, no acceptance problems

## Cortex Embedding Model Configuration

The sample pipeline must support two embedding modes:

- real embedding provider, when configured
- local deterministic placeholder vectors, when no provider is configured

Placeholder mode is acceptable for proving pipeline shape. It is not acceptable
for semantic search quality.

### Required Configuration

Add these environment variables when real embeddings are ready:

```bash
export SUNSHINE_EMBEDDING_PROVIDER=cortex
export CORTEX_BASE_URL=https://cortex.vallery.net
export CORTEX_API_KEY=...
export SUNSHINE_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
export SUNSHINE_EMBEDDING_DIMENSIONS=1024
```

Optional:

```bash
export SUNSHINE_EMBEDDING_BATCH_SIZE=64
```

The verified Cortex configuration uses `Qwen/Qwen3-Embedding-0.6B`. The output
dimensionality is 1,024. Keep direct embedding inputs small; for larger RAG
loads, use Cortex managed ingestion instead of direct bulk embedding.

The code should read configuration from environment variables only. Do not
commit API keys or local `.env` files.

### Provider Contract

The embedding layer should expose a small interface:

```python
class EmbeddingProvider:
    model: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...
```

Implementations:

- `PlaceholderEmbeddingProvider`
- `GeminiEmbeddingProvider`
- `OpenAICompatibleEmbeddingProvider` for Cortex

The sample pipeline should select:

- `OpenAICompatibleEmbeddingProvider` when `SUNSHINE_EMBEDDING_PROVIDER=cortex`
- `GeminiEmbeddingProvider` when `SUNSHINE_EMBEDDING_PROVIDER=gemini`
- `PlaceholderEmbeddingProvider` otherwise

### Placeholder Embeddings

Placeholder rows must include:

```json
{
  "embedding_status": "placeholder",
  "embedding_model": "local-placeholder",
  "semantic_quality": false
}
```

This prevents anyone from mistaking the tracer-bullet run for real semantic
search.

### Real Embeddings

Real embedding rows must include:

```json
{
  "embedding_status": "embedded",
  "embedding_provider": "cortex",
  "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
  "embedding_dimensions": 1024,
  "semantic_quality": true
}
```

### What You Need To Do

Before running with real embeddings:

1. Set `CORTEX_API_KEY` in your shell or deployment secret manager.
2. Set `CORTEX_BASE_URL=https://cortex.vallery.net`.
3. Set `SUNSHINE_EMBEDDING_PROVIDER=cortex`.
4. Set `SUNSHINE_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B`.
5. Set `SUNSHINE_EMBEDDING_DIMENSIONS=1024`.
6. Run a tiny embedding smoke test on one or two chunks.
7. Confirm the output says `embedding_status=embedded`, not `placeholder`.
8. Confirm embedding dimensions match the configured/vector-store expectation.

### Local Smoke Test Target

The implementation should provide a small command or test path equivalent to:

```bash
SUNSHINE_EMBEDDING_PROVIDER=cortex \
SUNSHINE_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B \
SUNSHINE_EMBEDDING_DIMENSIONS=1024 \
CORTEX_BASE_URL=https://cortex.vallery.net \
CORTEX_API_KEY=... \
python -m sunshine_extraction.sample_pipeline \
  --limit 2 \
  --input-root "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples" \
  --output-dir "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/sample-pipeline-smoke"
```

Expected smoke-test result:

- command exits successfully
- `sample-embeddings.jsonl` exists
- rows have `embedding_status=embedded`
- rows have `embedding_provider=cortex`
- rows have `embedding_model=Qwen/Qwen3-Embedding-0.6B`
- rows have `embedding_dimensions=1024`
- rows have numeric vectors
- summary reports `embedding_status.embedded > 0`

If any of those fail, fall back to placeholder mode and keep the pipeline
running while embedding configuration is fixed.
