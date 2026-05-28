# Docling OCR Integration Design

## Context

Sunshine currently has a custom OCR/extraction path:

- `extract_content` chooses extraction strategy from the existing extraction plan.
- `OcrExecutor` implementations return `OcrDocumentResult` and `OcrPageResult`.
- LangGraph nodes call `extract_content`, `validate_and_repair_extraction`, `quality_gate`, `chunk_content`, then embedding/tag/routing nodes.
- The current OCR stack has grown organically: local Tesseract, Cortex OCR, OpenAI escalation, handwritten/gibberish validation, and custom artifact rows.

This is useful but brittle. Docling is a mature document conversion toolkit with OCR support for scanned PDFs/images, layout parsing, table extraction, Markdown/JSON export, and standard/VLM pipelines. The upstream project documents standard PDF conversion, multiple OCR backends, full-page OCR, table structure extraction, VLM conversion, and OpenAI-compatible remote VLM execution.

The goal is not to replace our whole pipeline. The likely fit is to replace the fragile OCR/text extraction implementation while preserving our LangGraph orchestration, review dashboard, model usage accounting, confidence gates, tagging, placement, and audit artifacts.

## Decision Summary

Implement Docling as a new extraction provider behind our existing extraction boundary.

Recommended first implementation:

- Add `DoclingOcrExecutor` or `DoclingExtractionProvider`.
- Use Docling standard PDF/image conversion for scanned PDFs and image-like documents.
- Export Docling Markdown/plain text into our existing `ExtractionResult.text`.
- Preserve Docling JSON/structured metadata in `ExtractionResult.metadata`.
- Convert Docling page/text output into existing `sample-ocr-pages.jsonl`, `sample-ocr-documents.jsonl`, and `sample-extraction-results.jsonl`.
- Keep Cortex/OpenAI OCR as fallback/escalation until Docling proves better on our QA sample.
- Gate rollout by evaluation metrics, not by assumption.

Do not remove the current OCR stack in the first slice.

## Why Docling Is Relevant

Docling appears to solve several problems we are currently solving manually:

- OCR for scanned PDFs/images.
- PDF parsing with layout awareness.
- Table structure extraction.
- Export to Markdown, JSON, plain text, and doctags.
- Standard deterministic pipeline for normal documents.
- VLM pipeline for difficult page-image documents.
- Remote VLM support against OpenAI-compatible endpoints, which could point at Cortex or OpenAI.

This maps well to Sunshine document types:

- Scanned meeting minutes.
- Scrapbook pages with mixed text/images.
- Newspaper clippings.
- Financial reports and budget tables.
- Yearbook/proof-review pages.
- Image-only PDFs.

## Non-Goals

- Do not replace LangGraph.
- Do not replace tagging, embeddings, placement, or review routing.
- Do not modify source corpus files.
- Do not trust Docling blindly without side-by-side evaluation.
- Do not make OpenAI the default OCR path.
- Do not send customer documents to external APIs unless the run is explicitly configured for external services.

## Proposed Architecture

### Current Shape

```text
LangGraph
  load_file_context
  classify_content_type
  plan_extraction
  extract_content
    current custom extraction/OCR
  validate_text_extraction
    custom validation + OCR repair
  quality_gate
  chunk_content
  embed_chunks
  retrieve_labeled_examples
  assign_deterministic_tags
  inspect_tags_with_llm
  combine evidence / calibrate
  route_or_review
  persist artifacts
```

### Target Shape

```text
LangGraph
  load_file_context
  classify_content_type
  plan_extraction
  extract_content
    ExtractionProviderRouter
      native_text_provider
      docling_provider
      cortex_ocr_provider
      openai_ocr_provider
  validate_text_extraction
    quality validator
    optional escalation provider
  quality_gate
  chunk_content
  embed/tag/route/persist unchanged
```

## Provider Model

Introduce an explicit extraction provider interface:

```python
class ExtractionProvider(Protocol):
    provider_name: str

    def can_extract(self, sample: SampleFile, plan: dict[str, Any]) -> bool:
        ...

    def extract(
        self,
        sample: SampleFile,
        plan: dict[str, Any],
        artifacts: OcrArtifacts | None = None,
    ) -> ExtractionResult:
        ...
```

Initial providers:

- `NativeTextExtractionProvider`
  - Existing PDF/text extraction path for born-digital text.
- `DoclingExtractionProvider`
  - New Docling-based conversion.
- `CortexOcrProvider`
  - Existing Cortex OCR wrapper.
- `OpenAiOcrProvider`
  - Existing OpenAI-compatible vision OCR wrapper.

Compatibility layer:

- Keep `OcrExecutor` temporarily.
- Implement Docling through existing `OcrExecutor` first if that is faster.
- Move toward `ExtractionProvider` once `sample_pipeline.py` is refactored.

## Docling Modes

### Mode 1: Standard Docling Conversion

Use for:

- PDF documents.
- Image-only PDFs.
- Scanned documents.
- Financial tables.
- Printed newspaper clippings.

Expected output:

- Markdown text.
- Structured JSON metadata.
- Table-preserving Markdown where possible.
- Page-level artifacts if available.

Pipeline options:

- OCR enabled.
- Table structure enabled.
- Full-page OCR enabled for image-only/scanned PDFs where normal parsing is weak.
- CPU default first; GPU acceleration can be tested later.

### Mode 2: Docling VLM Pipeline

Use only after standard Docling evaluation.

Use for:

- Handwritten pages.
- Scrapbook pages with complex layout.
- Faint newspaper clippings.
- Pages where standard OCR returns gibberish or sparse text.

Potential targets:

- Local Docling VLM model on GPU.
- Cortex OpenAI-compatible VLM endpoint if available.
- OpenAI only as an explicit external escalation.

Risk:

- VLMs can hallucinate or summarize.
- For archival OCR, we need transcription fidelity, not interpretation.
- Must mark VLM output separately in artifacts and review UI.

## Routing Rules

Proposed first-pass provider routing:

| File/Plan State | First Provider | Escalation |
| --- | --- | --- |
| Born-digital PDF/text with valid text | Native text extraction | Docling if validation fails |
| Image-only PDF | Docling standard | Cortex OCR, then OpenAI if configured |
| Scanned document image | Docling standard | Cortex OCR, then OpenAI if configured |
| Spreadsheet | Existing spreadsheet metadata | No Docling in first slice |
| Photo metadata/image archive | Existing metadata path | Docling only if text-bearing image plan says OCR required |
| Publisher/technical/deferred | Existing defer path | None |

Important rule:

Docling should not automatically replace simple photo metadata extraction. We do not want every event photo routed through heavy document parsing.

## Data Mapping

### ExtractionResult

Map Docling output into:

- `extraction_status`
  - `extracted` when text/Markdown has useful content.
  - `metadata_extracted` when only metadata/layout exists.
  - `failed` when conversion fails.
- `text`
  - Prefer Markdown export.
  - Store plain text fallback if Markdown export fails.
- `metadata`
  - `provider: "docling"`
  - `docling_pipeline: "standard" | "vlm"`
  - `docling_ocr_engine`
  - `docling_backend`
  - `table_count`
  - `page_count`
  - `export_formats_available`
  - `conversion_seconds`
  - `docling_json_path` if persisted.
- `warnings`
  - `docling_conversion_failed:<error>`
  - `docling_sparse_text`
  - `docling_table_detected`
  - `docling_vlm_used`
  - `docling_external_service_used` if remote.

### OCR Artifacts

Create compatible rows:

- `sample-ocr-documents.jsonl`
  - one row per document.
  - `ocr_engine: "docling:<engine>"`
  - confidence may be `null` if Docling does not expose comparable confidence.
- `sample-ocr-pages.jsonl`
  - one row per page when possible.
  - if Docling only exports document-level Markdown, synthesize page rows conservatively or leave page rows empty and record document-level artifact.

### Model Usage

Model usage rows must be explicit:

- Docling standard OCR local CPU/GPU:
  - `provider: "docling"`
  - `model: <ocr/layout model or engine>`
  - `cost_basis: "local"`
  - `purpose: "ocr"` or `document_conversion`
- Docling VLM local:
  - `provider: "docling-vlm"` or `cortex`
  - `cost_basis: "local"`
- Docling remote/OpenAI:
  - `provider: "openai"` or endpoint provider
  - `cost_basis: "external"`
  - external cost estimated only when token usage and pricing are known.

## Evaluation Plan

Create a side-by-side run:

```text
qa_samples_docling_eval/
  current/
  docling_standard/
  docling_standard_plus_current_fallback/
```

Compare:

- OCR quality labels.
- Text length.
- Gibberish score.
- Empty-text rate.
- Poor-quality rate.
- Review-required rate.
- Tag accuracy against current golden labels.
- Table preservation for financial reports.
- Runtime per page/document.
- Local CPU/GPU resource usage.
- External calls and cost.

Required sample coverage:

- accepted scanned documents.
- image-only PDFs.
- newspaper articles.
- scrapbook pages.
- financial/budget packets.
- born-digital PDFs that previously looked like text but were actually image scans.
- handwritten pages.

## Success Criteria

### Functional

- Docling provider can process one PDF through `python -m sunshine_extraction.langgraph_pipeline --input-file ...`.
- Docling provider writes existing compatible artifacts.
- Dashboard can display Docling extraction snippets without schema changes.
- Run report shows Docling model usage/local runtime.
- Existing non-OCR extraction paths still work.

### Quality

On QA sample:

- Empty OCR rate decreases versus current pipeline.
- Gibberish OCR rate decreases versus current pipeline.
- No increase in lost-data cases.
- At least same or better tag routing accuracy after extraction.
- Financial reports preserve enough table structure for review.
- Review-required rate decreases only when quality genuinely improves.

### Safety

- No source files are modified.
- External API use is opt-in and visible in model usage.
- If Docling fails, current fallback path still runs.
- Every escalation is recorded in warnings and artifacts.
- VLM output is marked separately from deterministic OCR.

### Performance

- Single-file run completes within an acceptable review latency budget.
- Batch mode supports bounded concurrency.
- GPU use is optional, not required for API server startup.
- Large PDFs can be page-limited or run asynchronously without blocking dashboard responsiveness.

## Implementation Milestones

### Milestone 1: Spike and Compatibility Proof

Branch:

```bash
feature/docling-ocr-provider
```

Tasks:

- Add optional dependency group for Docling.
- Create `DoclingExtractionProvider` or `DoclingOcrExecutor`.
- Add CLI/env provider option:
  - `SUNSHINE_EXTRACTION_PROVIDER=docling`
  - or `SUNSHINE_OCR_PROVIDER=docling`
- Convert one PDF and one image through LangGraph.
- Persist Markdown/text and metadata.
- Add tests with tiny fixtures and mocked Docling converter.

Success:

- Existing tests pass.
- One single-file debug run produces `sample-pipeline-results.jsonl`, `sample-extraction-results.jsonl`, OCR artifact rows, and model usage rows.

### Milestone 2: Side-by-Side QA Evaluation

Tasks:

- Add dashboard preset: `qa_samples_docling_eval`.
- Run current provider and Docling provider on same QA sample.
- Generate comparison report:
  - text quality deltas.
  - review route deltas.
  - tag deltas.
  - runtime/cost deltas.

Success:

- We can point to exact files where Docling improved, regressed, or tied.
- No production default changes yet.

### Milestone 3: Provider Router

Tasks:

- Add provider routing policy:
  - native text first for born-digital text.
  - Docling first for scanned/image-only PDFs.
  - current Cortex/OpenAI escalation only after Docling quality failure.
- Add per-provider quality thresholds.
- Add dashboard filter for extraction provider.

Success:

- Run report separates `docling`, `cortex`, and `openai` extraction/model usage.
- Review UI makes it obvious which provider produced each result.

### Milestone 4: Production Default Decision

Tasks:

- Promote Docling for specific document classes only if QA metrics justify it.
- Keep fallback chain.
- Document operational requirements:
  - dependency install.
  - model cache location.
  - CPU/GPU behavior.
  - timeout/concurrency knobs.

Success:

- Production single-file pipeline can use Docling safely.
- Batch pipeline has bounded concurrency and clear cost/runtime reporting.
- Customer-facing no-lost-data requirement remains protected by review gates.

## Open Questions

- Does Docling expose page-level OCR confidence consistently across selected OCR backends?
- Which Docling OCR backend performs best on our historical scans: EasyOCR, RapidOCR, Tesseract CLI, or VLM?
- Can Cortex serve a Docling-compatible VLM endpoint, or do we keep Cortex OCR separate?
- Should Docling JSON be stored as an artifact per file for later layout/table inspection?
- What latency budget is acceptable for single-file production runs?
- Are handwritten documents better handled by Docling VLM, Cortex OCR, or OpenAI vision OCR?

## Recommended Next Step

Do a one-day spike, not a full replacement.

The first implementation should add Docling as an optional provider and run a side-by-side evaluation against our QA sample. We should only replace the current OCR default after the comparison proves Docling improves text quality without hiding review-needed cases.

## References

- Docling GitHub README: https://github.com/docling-project/docling
- Docling custom conversion example: https://docling-project.github.io/docling/examples/custom_convert/
- Docling pipeline options reference: https://docling-project.github.io/docling/reference/pipeline_options/
- Docling full-page OCR example: https://docling-project.github.io/docling/examples/full_page_ocr/
- Docling pipelines reference: https://docling-project.github.io/docling/examples/agent_skill/docling-document-intelligence/pipelines/
