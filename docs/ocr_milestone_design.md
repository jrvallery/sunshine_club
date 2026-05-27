# OCR Extraction Milestone Design

## Goal

Implement the first production-grade `ocr_page_level` executor for scanned
documents in the Sunshine Club pipeline.

The goal is to turn scanned PDFs, photographed documents, scrapbook pages, and
newspaper/article scans from deferred placeholders into searchable, auditable
text artifacts that can safely feed:

- chunking
- Gemini embeddings
- structured LLM tag inspection
- route/review decisions
- future grounded search and chat

This milestone should use the QA sample set first, then scale to the corrected
scanned-document corpus after quality gates prove it is safe.

## Why This Is Next

The QA sample pipeline now proves the full graph shape:

```text
classification
-> extraction plan
-> extraction
-> quality gate
-> chunks
-> embeddings
-> LLM/deterministic tags
-> route or review
```

But scanned documents currently stop at:

```text
extraction_status = deferred_extractor
warnings = ["ocr_executor_not_installed"]
```

That means the pipeline is not yet reading the actual content of the largest
and highest-value file class. For scanned docs, tags are currently based mostly
on filename/path/metadata. OCR is the next product milestone because it changes
the pipeline from "document metadata routing" to "document content
understanding."

## Product Promise

For every scanned document processed by OCR:

- preserve the original file untouched
- preserve page-level provenance
- extract text where possible
- record OCR quality and warnings
- never silently treat failed OCR as success
- route only when extraction evidence is strong enough
- send weak/failed/uncertain cases to review

No scanned document should lose data or disappear from the audit trail.

## Input Scope

Primary first-run input:

```text
/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples
```

Use the existing deterministic sample selection from the QA sample pipeline.

Initial OCR target rows:

- `accepted-scanned-document-random-100`, first 10 selected by the sample
  pipeline
- `changed-image-to-scanned_document-image_scan_policy_path_or_name`, first 5
- `changed-document-to-scanned_document-pdf_image_only_or_empty_text`, first 5

Expected initial OCR target count:

- 20 scanned-document QA rows

After the QA pass succeeds, expand to:

- all 100 accepted scanned-document QA samples
- all changed scanned-document sample folders
- selected review-required scrapbook/newspaper PDFs

Do not run corpus-wide OCR until the QA report proves quality and runtime are
acceptable.

## Outputs

Write OCR outputs under the existing sample pipeline output directory:

```text
/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/sample-pipeline-ocr/
```

Required OCR artifacts:

- `sample-ocr-pages.jsonl`
- `sample-ocr-documents.jsonl`
- `sample-ocr-summary.json`

The existing sample pipeline artifacts should also be produced:

- `sample-inputs.jsonl`
- `sample-extraction-results.jsonl`
- `sample-chunks.jsonl`
- `sample-embeddings.jsonl`
- `sample-llm-tag-inspections.jsonl`
- `sample-tag-candidates.jsonl`
- `sample-pipeline-results.jsonl`
- `sample-pipeline-summary.json`

No source file should be moved, modified, deleted, or overwritten.

## OCR Executor Design

### Strategy

Implement `ocr_page_level` as a real extraction executor.

Supported input types for this milestone:

- image files: `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff`
- scanned PDFs

Initial implementation should prefer a local OCR engine so customer data does
not leave the machine during OCR.

Recommended first engine:

- Tesseract OCR through `pytesseract`

Recommended PDF page rasterization:

- `pypdfium2` or another local PDF renderer

If the runtime dependency is missing, the executor must preserve current
behavior:

```text
extraction_status = deferred_extractor
warnings = ["ocr_executor_not_installed"]
```

### Page-Level Record

Each `sample-ocr-pages.jsonl` row should include:

```json
{
  "source_path": "...",
  "relative_path": "...",
  "sample_path": "...",
  "page_number": 1,
  "page_count": 4,
  "ocr_engine": "tesseract",
  "ocr_engine_version": "...",
  "ocr_status": "ok",
  "text": "...",
  "text_length": 1240,
  "mean_confidence": 82.4,
  "word_count": 210,
  "image_width": 2550,
  "image_height": 3300,
  "warnings": []
}
```

### Document-Level Record

Each `sample-ocr-documents.jsonl` row should include:

```json
{
  "source_path": "...",
  "relative_path": "...",
  "sample_path": "...",
  "ocr_status": "ok",
  "page_count": 4,
  "pages_ok": 4,
  "pages_failed": 0,
  "total_text_length": 8120,
  "mean_confidence": 79.8,
  "quality": "ok",
  "warnings": []
}
```

## Quality Gate

OCR extraction should map into the existing extraction quality gate.

Proposed quality rules:

- `ok`: non-empty text and average confidence at or above threshold
- `poor`: some text extracted, but confidence below threshold or very sparse
  text
- `metadata_only`: no text, but image/page metadata extracted
- `deferred`: OCR engine missing or unsupported file type
- `failed`: OCR attempted but file/page could not be read

Initial thresholds:

- document mean OCR confidence >= `60` -> `ok`
- document text length >= `100` chars -> text is usable
- pages failed <= `20%` -> acceptable partial OCR

These thresholds are starting points. The QA report should expose them so they
can be adjusted.

## Pipeline Integration

Update `extract_content` for `ocr_page_level`:

Current:

```text
deferred_extractor + metadata chunk
```

Target:

```text
real OCR pages
-> document text
-> quality gate
-> text chunks
-> Gemini embeddings
-> structured LLM tag inspection
-> route/review decision
```

For OCR `ok` documents:

- `extraction_status = extracted`
- `quality = ok`
- `can_chunk = true`
- `can_embed = true`
- LLM receives OCR text excerpt
- route is allowed if tag confidence passes gate

For OCR `poor` documents:

- chunk extracted text
- embed if text is usable
- route should usually become review unless tag evidence is very strong

For OCR `failed` documents:

- do not route
- emit explicit review/failure reason

## LLM Tagging After OCR

After OCR, the structured LLM tag inspector should receive:

- path
- filename
- final class
- document subtype
- OCR status
- OCR confidence summary
- page count
- deterministic tag candidates
- OCR text excerpt

The LLM should not receive raw image/PDF bytes in this milestone.

The combined tag decision should continue to require evidence:

- deterministic rule evidence
- OCR text evidence
- optional LLM agreement

LLM disagreement should not silently override deterministic or OCR evidence.

## Success Criteria

### Functional

- The sample pipeline has a real `ocr_page_level` executor.
- Image-based scanned docs can be OCRed.
- Scanned PDFs can be rasterized and OCRed page by page.
- OCR emits page-level rows.
- OCR emits document-level rows.
- OCR text flows into chunks.
- OCR chunks flow into Gemini embeddings when configured.
- OCR text flows into structured LLM tag inspection when enabled.
- OCR failures are explicit and auditable.
- Source files are never modified.

### QA Sample Acceptance

On the 36-file QA sample pipeline:

- all 36 selected files still produce exactly one final result row
- all 20 scanned-document rows attempt real OCR or explicit technical defer
- `ocr_executor_not_installed` appears only when dependencies are actually
  missing
- at least 10 of the 20 scanned-document QA rows produce non-empty OCR text
- `sample-ocr-pages.jsonl` exists
- `sample-ocr-documents.jsonl` exists
- `sample-ocr-summary.json` exists
- `sample-pipeline-summary.json` includes OCR status counts
- no OCR row is silently marked successful with empty text

### Quality Acceptance

For the first QA OCR run:

- OCR page records include confidence when the engine provides it
- OCR document records include page counts and failed-page counts
- low-confidence OCR is marked `poor` or review-required
- scanned documents with good OCR can move from:

```text
review_or_extraction_deferred
```

to either:

```text
route_candidate
```

or:

```text
review_low_confidence_tag
```

but not remain deferred solely because OCR is missing.

### Safety Acceptance

- No source files are moved, deleted, renamed, or overwritten.
- OCR output is written only to manifest/output folders.
- Original page images/PDFs remain the authoritative source.
- Every failed page has a warning.
- Every failed document has a review reason.
- A run can be repeated without changing source data.

### Testing Acceptance

Tests should cover:

- OCR engine missing -> deferred extractor
- image OCR success path
- scanned PDF page rasterization path
- per-page OCR failure captured without stopping whole run
- OCR document quality gate
- OCR text chunking
- OCR text passed into LLM tag prompt
- one scanned input produces OCR page rows, OCR document row, chunks, and one
  final pipeline result

### Runtime Acceptance

For the first 20 scanned-document QA rows:

- run completes without crashing
- runtime is recorded in summary
- average seconds per page is recorded
- failed-page rate is recorded

Do not start corpus-wide OCR until runtime and failure rate are known.

## Non-Goals

- Do not implement cloud OCR in this milestone unless local OCR quality is
  unusable.
- Do not write OCR outputs to Postgres yet.
- Do not mutate Google Drive.
- Do not claim OCR text is perfect.
- Do not auto-route low-confidence OCR records without review.
- Do not solve handwriting OCR as a first requirement.

## Open Decisions

- Exact OCR engine: Tesseract first unless QA quality is unacceptable.
- PDF renderer: choose based on installability and output quality on the Atlas
  environment.
- Confidence thresholds: start with the proposed thresholds and adjust from QA
  evidence.
- Whether OCR should process every page of large scrapbook PDFs in one run or
  cap pages for the first pass.

## Recommended Implementation Steps

1. Add OCR dependency detection and version reporting.
2. Implement image OCR for one page/image.
3. Implement scanned PDF rasterization and per-page OCR.
4. Add `sample-ocr-pages.jsonl`, `sample-ocr-documents.jsonl`, and
   `sample-ocr-summary.json`.
5. Replace the `ocr_page_level` placeholder in the sample pipeline.
6. Add tests for success, failure, and missing dependency behavior.
7. Run the 36-file QA sample pipeline.
8. Review OCR quality and route/tag changes.
9. Decide whether to expand to the larger scanned-document QA set.

## Implementation Result

Implemented in:

- `packages/extraction/src/sunshine_extraction/sample_pipeline.py`
- `tests/test_sample_pipeline.py`

Runtime notes:

- Python dependencies: `pytesseract`, `pypdfium2`
- OCR engine: Tesseract `5.5.0`
- Atlas does not currently have system Tesseract installed through `apt`.
  A local non-root runtime was extracted under `.local/tesseract/` and is
  ignored by git. The executor detects that local runtime automatically.

Latest QA OCR run:

```bash
SUNSHINE_EMBEDDING_PROVIDER=placeholder \
python -m sunshine_extraction.sample_pipeline \
  --input-root "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples" \
  --output-dir "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/sample-pipeline-ocr" \
  --quiet
```

Artifacts written:

- `sample-ocr-pages.jsonl`
- `sample-ocr-documents.jsonl`
- `sample-ocr-summary.json`
- all standard sample pipeline artifacts

Latest run results:

- selected samples: 36
- pipeline result rows: 36
- OCR document rows: 20
- OCR page rows: 49
- non-empty OCR documents: 17
- OCR status:
  - `ok`: 11
  - `poor`: 6
  - `empty`: 3
- route status:
  - `route_candidate`: 27
  - `review_ocr_quality`: 6
  - `review_ocr_no_text`: 3
- failed OCR pages: 0
- failed page rate: 0.0
- total OCR seconds: 122.8222
- average seconds per page: 2.5062

Verification:

- `pytest`: 59 passed
- dashboard build: passed
- OCR acceptance audit: passed
