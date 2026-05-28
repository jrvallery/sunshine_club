# LangGraph Open-Source Provider Strategy

## Purpose

The goal is to avoid reinventing mature open-source systems while preserving the parts of Sunshine that need to remain deterministic, auditable, and customer-specific.

Sunshine should keep **LangGraph as the control plane**. Open-source tools should be used as providers inside graph nodes, not as uncontrolled replacements for the graph itself.

This document reviews every major LangGraph stage and recommends:

- the current implementation status.
- candidate open-source providers.
- the number-one recommended provider or in-house approach.
- implementation strategy.
- success criteria.
- when not to over-engineer.

## Guiding Principle

```text
LangGraph owns orchestration, state, audit, routing, and human review.
Providers own specialized capabilities like parsing, OCR, chunking, embeddings, retrieval, reranking, connectors, and observability.
```

The pipeline should become:

```text
LangGraph node
  provider interface
    selected provider implementation
  normalized Sunshine artifact
  validation gate
  deterministic routing decision
```

Not:

```text
External RAG platform owns the workflow
  unknown state
  unclear review gates
  unclear model usage
  hard-to-audit output
```

## Current Graph

Current production graph:

```text
load_file_context
classify_content_type
plan_extraction
extract_content
validate_text_extraction
quality_gate
chunk_content
embed_chunks
retrieve_labeled_examples
assign_deterministic_tags
inspect_tags_with_llm
combine_tag_evidence
calibrate_tag_confidence
resolve_route_or_review
persist_outputs
```

Current graph source:

```text
packages/extraction/src/sunshine_extraction/graph/build.py
packages/extraction/src/sunshine_extraction/graph/nodes/
```

## Provider Strategy Summary

| Graph Area | Recommended Default | Use OSS? | Why |
| --- | --- | --- | --- |
| Workflow orchestration | LangGraph in-house graph | Keep current | Deterministic state, explicit routing, HITL review, audit artifacts. |
| Durable batch execution | Temporal later | Use OSS/runtime | Durable retries/cancel/resume, but defer until providers stabilize. |
| Connectors/ingestion | Onyx connectors first; LlamaIndex readers second | Evaluate | Avoid building every source connector. |
| File identity/loading | In-house | Keep current | Simple, customer-specific, audit-sensitive. |
| Content type classification | In-house plus optional libmagic/Tika signals | Mostly in-house | Classes map to Sunshine policy, not generic MIME only. |
| Extraction planning | In-house | Keep current | This is policy. Provider choice can be data-driven later. |
| OCR/document parsing | Docling first | Use OSS | Best direct library fit for layout/OCR/tables without replacing app. |
| Parser benchmark candidates | Docling, MinerU, RAGFlow DeepDoc, Unstructured | Use OSS | Need measured quality by document type. |
| Text validation/repair | In-house with optional language-tool signals | Keep current | No-lost-data gates are customer-specific. |
| Chunking | Docling/Unstructured structure-aware chunks first; in-house fallback | Hybrid | Structure-aware chunks matter, but final chunk policy is domain-specific. |
| Embeddings | Cortex/OpenAI via provider interface | Keep current plus add caching | Simple enough; avoid adopting a platform just for embeddings. |
| Vector index | Qdrant | Use OSS | Mature local/server vector DB with filtering and hybrid search options. |
| Keyword/hybrid search | OpenSearch if needed later | Use OSS later | Better for large-scale lexical search, heavier ops. |
| Retrieval orchestration | Haystack components | Evaluate | Good modular retriever/ranker pipelines without replacing graph. |
| Reranking | Cortex reranker first; Haystack adapter later | Hybrid | Keep local first; wrap rerankers behind provider interface. |
| LLM tag inspection | Cortex/OpenAI via LangChain structured output | Keep current/providerize | Small, auditable, taxonomy-specific. |
| Confidence calibration | In-house | Keep current | Business risk policy, not generic RAG functionality. |
| Routing/review decision | In-house | Keep current | No-lost-data guarantees live here. |
| Human review dashboard | In-house, borrow UX ideas | Keep current | Review semantics are project-specific. |
| Observability/tracing | Langfuse now; Phoenix eval later | Use OSS | Trace model calls and RAG quality. |
| Evaluation | In-house gates plus Ragas/DeepEval/Phoenix experiments | Hybrid | Our gates are domain-specific; OSS helps standard RAG metrics. |
| Persistence/artifacts | In-house normalized artifacts | Keep current | Auditability and dashboard depend on stable artifacts. |

## Provider Interface Pattern

Every provider should follow this pattern:

```python
class ProviderResult(TypedDict):
    status: str
    output: dict
    warnings: list[str]
    metrics: dict
    model_usage: list[dict]
    artifacts: list[dict]


class Provider(Protocol):
    provider_name: str

    def run(self, state: DocumentPipelineState, config: dict) -> ProviderResult:
        ...
```

Rules:

- Providers do not decide final routing.
- Providers do not mutate source files.
- Providers must return normalized artifacts.
- Providers must report external calls.
- Providers must be replaceable per run.
- Providers must fail closed into review, not silently accept.

## 1. Workflow Orchestration

### Current

LangGraph builds and runs the document intelligence graph. The graph has explicit typed state and auditable node boundaries.

### Candidates

- LangGraph.
- Langflow visual builder.
- Dify workflows.
- RAGFlow workflows.
- Haystack pipelines.

### Recommendation

**Number-one default: keep LangGraph.**

Do not replace LangGraph with Langflow, Dify, RAGFlow, or Haystack. Those tools can provide components or inspiration, but LangGraph is the best fit for deterministic file-by-file state transitions, conditional routing, and human-review gates.

### Why

LangGraph gives us:

- deterministic node order.
- explicit state object.
- conditional branches.
- checkpoint support.
- testable Python code.
- clear graph visualization.
- controllable HITL boundaries.

### Implementation Strategy

- Keep graph topology in `graph/build.py`.
- Continue grouping nodes by phase.
- Add provider interfaces under `sunshine_extraction/providers/`.
- Make node code thin:
  - resolve provider.
  - call provider.
  - normalize result.
  - update state.

### Success Criteria

- Every provider call is visible in `graph-audit-events.jsonl`.
- Every provider call can be enabled/disabled per run.
- Replacing a provider does not change graph topology.
- Unit tests can mock each provider.

## 2. Durable Execution

### Current

Dashboard starts runs through FastAPI/subprocess execution. Batch runs aggregate per-file LangGraph artifacts.

### Candidates

- Temporal.
- Celery/RQ.
- Prefect/Dagster.
- Continue subprocess runner.

### Recommendation

**Number-one default: Temporal, but later.**

Temporal should not replace LangGraph. It should wrap batch execution:

```text
Temporal workflow: BatchRun
  activity: select files
  activity: run single-file LangGraph
  activity: import artifacts
  activity: update run status
```

### Why

Temporal gives durable retries, cancellation, resume, schedules, and long-running reliability. That matters for production, but implementing it before provider selection stabilizes would add complexity too early.

### Implementation Strategy

- Keep current subprocess runner for provider evaluation.
- Define Temporal workflow contracts now, implement later:
  - `RunBatchPipeline`
  - `RunSingleFilePipeline`
  - `ImportRunArtifacts`
  - `CancelRun`
- Use Temporal only after single-file graph/provider behavior is stable.

### Success Criteria

- A killed worker can resume batch state.
- Dashboard cancellation stops future file processing.
- Per-file failures do not kill the whole batch.
- Retry policy is provider-specific.
- Existing artifact format is unchanged.

## 3. Connectors And Ingestion

### Current

The current pipeline primarily operates on mounted filesystem manifests and QA sample folders. Broader connectors are not built out.

### Candidates

- Onyx connectors.
- LlamaIndex readers/LlamaHub.
- Airbyte.
- RAGFlow knowledge-base connectors.
- Custom filesystem connector.

### Recommendation

**Number-one default: Onyx for connector inspiration/reuse, LlamaIndex readers for library-level ingestion.**

Use Onyx if we need enterprise-style connectors and search ingestion patterns. Use LlamaIndex readers when we only need lightweight Python loaders.

### Why

Connectors are a wheel we should avoid reinventing. But Sunshine’s current corpus is filesystem-heavy, so we do not need a full connector platform immediately.

### Implementation Strategy

Milestone 1:

- Keep filesystem ingestion in-house.
- Add a `SourceConnector` interface:

```python
class SourceConnector(Protocol):
    def list_documents(self) -> Iterable[SourceDocument]:
        ...
```

Milestone 2:

- Evaluate LlamaIndex readers for Google Drive, local folders, and common docs.
- Evaluate Onyx connectors if customer asks for SaaS/workspace ingestion.

### Success Criteria

- Every ingested document has stable `source_id`, `source_path`, `relative_path`, and content hash.
- Connector output is deterministic and replayable.
- Connector sync never modifies source files.
- Incremental sync can detect added/changed/deleted files.

## 4. File Identity And Loading

### Current

`load_file_context` validates a file exists and builds `SampleFile`.

### Candidates

- In-house.
- Fsspec.
- LlamaIndex `Document`.

### Recommendation

**Number-one default: in-house.**

This is small and audit-sensitive. Do not add a framework just to construct file identity.

### Implementation Strategy

- Keep current node.
- Add stable file IDs:
  - source path hash.
  - content hash.
  - source collection.
- Add file-size and mtime metadata.

### Success Criteria

- Same source file maps to same stable ID across runs.
- Missing files fail closed to review.
- Source file is never changed.

## 5. Content Type Classification

### Current

Simple extension/MIME/path based content class assignment.

### Candidates

- In-house rules.
- Python `mimetypes`.
- libmagic/python-magic.
- Apache Tika/Extractous.
- Docling/MinerU parser probe.
- LLM inspection.

### Recommendation

**Number-one default: in-house classifier plus libmagic/Tika-style metadata signals later.**

Content classes are Sunshine policy classes, not just generic MIME types. Open-source tools can provide signals, but not final policy.

### Implementation Strategy

- Keep current deterministic classifier.
- Add optional `FileProbeProvider`.
- Probe output:
  - MIME type.
  - extension.
  - encryption/locked status.
  - page count.
  - embedded text presence.
  - image-only PDF signal.
  - media type.
- Use probe signals to improve confidence, not replace policy.

### Success Criteria

- No file is discarded because of classifier uncertainty.
- Unknown/ambiguous files route to review or technical defer.
- PDF image-only vs born-digital text is identified before extraction when possible.
- `.pub` and unsupported technical files remain safely deferred.

## 6. Extraction Planning

### Current

`plan_extraction` maps content class to strategy.

### Candidates

- In-house.
- Provider router rules.
- LLM planning.

### Recommendation

**Number-one default: in-house provider router.**

Planning is policy. OSS tools should not decide whether a customer file is safe to auto-route.

### Implementation Strategy

Create:

```python
ExtractionProviderRouter
  choose_provider(sample, content_class, probe, run_config)
```

Provider selection should be explicit:

- born-digital PDF/text -> native text first.
- scanned/image-only PDF -> Docling first.
- complex table PDF -> Docling or MinerU benchmark winner.
- failed/sparse/gibberish -> escalation provider.
- technical formats -> defer.

### Success Criteria

- Provider choice is recorded in final result.
- Provider choice is reproducible from state and config.
- Provider fallback chain is visible in warnings/model usage.
- No implicit external calls.

## 7. OCR And Document Parsing

### Current

Custom extraction path with PDF text extraction, Tesseract, Cortex OCR, OpenAI OCR escalation, validation, and repair.

### Candidates

- Docling.
- MinerU.
- RAGFlow DeepDoc.
- Unstructured.
- Apache Tika / Extractous.
- Marker.
- PaddleOCR/RapidOCR/EasyOCR directly.
- Cortex/OpenAI vision OCR.

### Recommendation

**Number-one default: Docling as first integrated parsing provider.**

Benchmark candidates:

1. Docling.
2. MinerU.
3. RAGFlow DeepDoc.
4. Unstructured.
5. Current Cortex/OpenAI chain.

### Why Docling First

Docling is a library/toolkit that fits inside our graph. It supports PDF/image conversion, OCR, layout, tables, Markdown/JSON export, and VLM-style options without requiring us to adopt a full external RAG platform.

RAGFlow DeepDoc and MinerU may be excellent, but they are better evaluated after Docling because their integration shape is heavier or less directly aligned with our current Python provider seam.

### Implementation Strategy

- Add `DoclingExtractionProvider`.
- Keep current OCR as fallback.
- Add run config:
  - `SUNSHINE_EXTRACTION_PROVIDER=current|docling|mineru|ragflow|auto`
- Persist provider output:
  - Markdown text.
  - JSON structure path.
  - page/table metadata.
  - provider warnings.
- Add side-by-side run preset:
  - `qa_samples_parser_benchmark`.

### Success Criteria

- Empty OCR rate decreases.
- Gibberish rate decreases.
- Table preservation improves or remains equivalent.
- Review-required rate decreases only when quality improves.
- Runtime is acceptable for single-file production.
- No hidden external API calls.
- Source files remain untouched.

## 8. Text Validation And Repair

### Current

In-house validation detects empty/sparse/gibberish/distorted text and triggers OCR repair/escalation.

### Candidates

- In-house validators.
- LanguageTool.
- ftfy.
- textstat/readability heuristics.
- LLM critique.
- Parser-specific confidence.

### Recommendation

**Number-one default: in-house validation.**

This is a no-lost-data safety layer. It must remain conservative and domain-specific.

### Implementation Strategy

- Keep existing validator.
- Add provider-aware signals:
  - parser confidence if available.
  - table distortion score.
  - OCR glyph noise score.
  - text length by page.
  - repeated character/noise ratio.
- Use LLM critique only as a secondary signal, never as sole accept gate.

### Success Criteria

- Bad OCR does not get accepted because a provider says it is fine.
- Known bad examples fail validation.
- Known good examples pass.
- Validation reason is visible in review dashboard.

## 9. Quality Gate

### Current

In-house gate maps extraction result to `ok`, `poor`, `metadata_only`, `empty`, `failed`, `deferred`.

### Candidates

- In-house.
- RAGAS/DeepEval/Phoenix metrics.
- Parser confidence.

### Recommendation

**Number-one default: in-house.**

Quality gate is an operational safety policy. OSS metrics can inform it but should not own it.

### Implementation Strategy

- Keep current labels.
- Make thresholds configurable by document type.
- Add provider-specific quality evidence.
- Add dashboard breakdown by provider and quality.

### Success Criteria

- Quality labels match human review expectations.
- Low quality routes to review or fallback.
- Quality labels are stable across reruns.

## 10. Chunking

### Current

Custom chunking from extraction text/metadata.

### Candidates

- Docling structure-aware output.
- Unstructured chunking.
- LlamaIndex node parsers.
- Haystack preprocessors.
- LangChain text splitters.
- In-house archival chunker.

### Recommendation

**Number-one default: hybrid: Docling/Unstructured structure-aware chunks when available, in-house archival chunker as final policy.**

Do not adopt generic recursive text splitting as the primary strategy for archival documents. We need page-aware, table-aware, source-aware, and review-aware chunks.

### Implementation Strategy

Create `ChunkProvider`:

```python
class ChunkProvider(Protocol):
    def chunk(extraction: ExtractionResult, quality: dict) -> list[Chunk]:
        ...
```

Provider priority:

1. If parser returns sections/tables/pages, preserve those boundaries.
2. If no structure, use in-house chunker.
3. Attach page numbers, table IDs, parser provider, and text span metadata.

Benchmark:

- current chunker.
- Docling-derived structure chunks.
- Unstructured chunking.
- LlamaIndex semantic/markdown node parser.

### Success Criteria

- Chunks preserve source path and page/table context.
- Retrieval returns useful snippets with citations.
- Tables are not shredded into meaningless chunks.
- Scrapbook/newspaper pages keep page context.
- Chunk count stays bounded.

## 11. Embeddings

### Current

Provider interface supports Cortex/OpenAI and placeholder fallback. Gemini was removed from callable providers.

### Candidates

- Cortex local embeddings.
- OpenAI embeddings.
- SentenceTransformers.
- FastEmbed.
- Hugging Face TEI.
- LlamaIndex/Haystack embedding wrappers.

### Recommendation

**Number-one default: Cortex embeddings.**

Keep the current provider interface. Add caching and evaluation before adding more providers.

### Why

Embeddings are already simple enough. The real missing pieces are:

- stable cache by text hash/model.
- quality evaluation.
- vector index.
- fallback policy.

### Implementation Strategy

- Add embedding cache:
  - key: provider, model, dimensions, text hash.
- Store vectors in chosen index.
- Record model usage call count accurately.
- Allow OpenAI as explicit external alternative.

### Success Criteria

- No duplicate embedding calls for unchanged chunks.
- Embedding provider failure fails closed in eval mode.
- Dashboard shows provider/model/dimensions.
- Retrieval quality improves against golden labels.

## 12. Vector Index

### Current

SQLite semantic index exists for golden-label retrieval, but production-grade vector/hybrid search is not yet central.

### Candidates

- Qdrant.
- LanceDB.
- Chroma.
- Weaviate.
- Milvus.
- OpenSearch.
- Postgres pgvector.

### Recommendation

**Number-one default: Qdrant.**

Qdrant is a good balance for local/server deployment, metadata filtering, vector search, hybrid options, and operational simplicity.

### Alternative

Use OpenSearch later if lexical/hybrid search at scale becomes more important than vector-first retrieval.

### Implementation Strategy

- Add `VectorStoreProvider`.
- Start with local/dev Qdrant container or file-backed mode if suitable.
- Index:
  - chunk text.
  - embedding vector.
  - source path.
  - document type.
  - primary/secondary tags.
  - review/golden label status.
  - provider metadata.
- Keep SQLite dashboard DB as system-of-record for runs/reviews.

### Success Criteria

- Retrieval supports metadata filters.
- Re-indexing is idempotent.
- Search results include source citations.
- Golden-label similarity retrieval improves over current SQLite-only path.

## 13. Retrieval And Reranking

### Current

Semantic examples are retrieved from a local semantic index. Reranking is not a mature separate provider.

### Candidates

- Haystack retriever/ranker pipelines.
- LlamaIndex retrievers.
- Qdrant hybrid retrieval.
- Cortex reranker.
- Cohere/Jina/BAAI rerankers.
- OpenSearch BM25/hybrid.

### Recommendation

**Number-one default: Qdrant retrieval plus Cortex reranker. Evaluate Haystack as orchestration library for retrieval experiments.**

Do not replace LangGraph retrieval node with a full RAG platform. Instead, make retrieval providerized.

### Implementation Strategy

Create:

```python
RetrievalProvider
RerankProvider
```

Initial:

- Qdrant dense retrieval.
- optional lexical fallback.
- Cortex reranker.

Evaluation:

- compare Qdrant-only vs Qdrant+Cortex rerank vs Haystack pipeline.

### Success Criteria

- Golden-label nearest examples are relevant.
- Retrieval returns exact source/chunk citations.
- Reranking improves top-3 relevance.
- Retrieval latency stays acceptable.

## 14. LLM Calls

### Current

LLM tag inspection uses Cortex/OpenAI-compatible structured output. Gemini was removed from callable providers.

### Candidates

- Cortex local OpenAI-compatible model.
- OpenAI.
- LiteLLM gateway.
- LangChain structured output.
- Instructor/PydanticAI.
- Guardrails.

### Recommendation

**Number-one default: Cortex through OpenAI-compatible client; OpenAI explicit fallback only.**

Add a thin model gateway abstraction only if provider sprawl grows. Do not add LiteLLM until we have more than two production model targets.

### Implementation Strategy

- Keep `LLMTagInspector`.
- Strengthen schema validation.
- Fail closed on invalid primary tags.
- Add prompt/version metadata.
- Cache LLM tag results by input hash/model/prompt version.
- Add rate limits per provider.

### Success Criteria

- Invalid structured output routes to review.
- External model calls are visible and costed.
- Cortex is preferred when configured.
- OpenAI is never called implicitly.
- Repeated runs reuse cached tag inspections when inputs are identical.

## 15. Deterministic Tagging

### Current

In-house rules produce deterministic tag candidates from path/name/text/taxonomy.

### Candidates

- In-house.
- LLM classification.
- Zero-shot classifier models.
- Haystack/LlamaIndex classifiers.

### Recommendation

**Number-one default: in-house deterministic tag candidate generation.**

This is Sunshine taxonomy logic. OSS tooling can help classify text, but it cannot encode customer-specific routing policy safely.

### Implementation Strategy

- Keep deterministic candidates.
- Move rules out of `sample_pipeline.py` into taxonomy/rules data.
- Add rule IDs and evidence spans.
- Allow LLM/semantic retrieval to influence confidence, not replace deterministic evidence.

### Success Criteria

- Every auto tag has evidence.
- Rules are editable/testable.
- Known examples produce stable candidates.
- Bad examples route to review.

## 16. Tag Evidence Combination

### Current

Combines deterministic candidates, LLM inspection, and semantic examples.

### Candidates

- In-house.
- LlamaIndex/Haystack retrieval scores.
- Learning-to-rank later.

### Recommendation

**Number-one default: in-house.**

Evidence combination is an audit and risk policy, not a generic RAG function.

### Implementation Strategy

- Add explicit evidence model:
  - source: deterministic/semantic/llm/human.
  - confidence.
  - evidence text.
  - conflict flag.
- Store evidence rows separately for dashboard inspection.

### Success Criteria

- Reviewers can see why a tag was proposed.
- LLM disagreement is visible.
- Semantic example conflict is visible.
- No tag is accepted without evidence.

## 17. Confidence Calibration

### Current

In-house confidence calibration adjusts confidence based on extraction quality, LLM validity, semantic conflicts, and embeddings.

### Candidates

- In-house.
- sklearn/calibrated classifiers later.
- RAGAS/DeepEval metrics.

### Recommendation

**Number-one default: in-house now, data-trained calibration later.**

Do not outsource this. It encodes the no-lost-data posture.

### Implementation Strategy

- Keep rules transparent.
- Add calibration factor rows.
- Use golden labels to measure false-accept rate.
- Consider statistical calibration only after enough labeled data exists.

### Success Criteria

- High confidence accepted files are actually correct in golden evals.
- Low confidence or conflicting evidence routes to review.
- Calibration factors are visible in report/dashboard.

## 18. Routing And Human Review

### Current

Route/review logic is in-house and writes review queue artifacts imported into dashboard DB.

### Candidates

- In-house.
- Humanloop/Label Studio.
- Argilla.
- RAGFlow/Dify review UIs.

### Recommendation

**Number-one default: in-house dashboard and routing.**

The review workflow is central product behavior. Use open-source review tools only if labeling needs grow beyond the dashboard.

### Implementation Strategy

- Keep route statuses.
- Add reason taxonomy.
- Add provider-output comparison views.
- Add review decisions as golden labels.
- Add run-to-run diffing by provider.

### Success Criteria

- Reviewers can understand why a file needs review.
- Review decisions improve future runs.
- Accepted files are auditable.
- Nothing is silently dropped.

## 19. Persistence And Audit Artifacts

### Current

JSONL artifacts plus dashboard SQLite DB.

### Candidates

- In-house artifacts.
- MLflow artifacts.
- Langfuse traces.
- Phoenix traces/evals.
- Object storage later.

### Recommendation

**Number-one default: keep in-house normalized artifacts. Add tracing providers, not replacements.**

Artifacts are our contract between graph, dashboard, evaluation, and review. Do not replace them with a vendor/tool schema.

### Implementation Strategy

- Keep current JSONL files.
- Add provider-specific artifact paths.
- Store raw parser JSON separately when useful.
- Add artifact manifest with hash/row count.

### Success Criteria

- Every run can be audited offline.
- Artifacts are stable across provider swaps.
- Dashboard import remains backward-compatible.
- Raw provider artifacts can be inspected when needed.

## 20. Observability

### Current

Project has Langfuse dependency and model usage rows, but tracing is not fully central.

### Candidates

- Langfuse.
- Arize Phoenix.
- OpenTelemetry.
- MLflow.
- Weights & Biases.

### Recommendation

**Number-one default: Langfuse for model-call traces, Phoenix for RAG evaluation experiments later.**

Langfuse is already in dependencies. Phoenix is useful for open-source LLM/RAG observability and eval workflows, but adding both immediately may be too much.

### Implementation Strategy

- Normalize model usage rows first.
- Add Langfuse trace IDs to model usage.
- Keep OpenTelemetry spans around graph nodes.
- Evaluate Phoenix once retrieval and RAG answers are more mature.

### Success Criteria

- Every external/local model call is traceable.
- Run report shows tokens/cost/runtime.
- Provider failures are visible.
- Trace IDs link dashboard rows to observability backend.

## 21. Evaluation

### Current

Golden label evals and readiness gates exist in-house. Pipeline eval artifacts are dashboard-visible.

### Candidates

- In-house eval gates.
- Ragas.
- DeepEval.
- Phoenix evals.
- TruLens.
- promptfoo.

### Recommendation

**Number-one default: in-house evaluation gates, with Ragas/Phoenix added for RAG-answer quality later.**

For classification/OCR/routing, our metrics are domain-specific. For generated answers over indexed content, OSS RAG eval frameworks become more useful.

### Implementation Strategy

- Keep current golden-label eval.
- Add provider benchmark eval:
  - OCR/parser quality.
  - chunk retrieval quality.
  - tag accuracy.
  - route decision accuracy.
  - external cost.
- Later add Ragas/Phoenix metrics for final Q&A/chat behavior.

### Success Criteria

- Provider changes require eval comparison.
- False accepts are measured and gated.
- OCR regressions are caught.
- Retrieval quality is measured by golden labels.
- Cost and latency are measured per provider.

## 22. RAG Application Layer

### Current

The project is not yet a full end-user RAG chat/search product. It is building ingestion, extraction, tagging, review, and organization first.

### Candidates

- Onyx.
- RAGFlow.
- Dify.
- AnythingLLM.
- Open WebUI.
- Custom dashboard/search UI.

### Recommendation

**Number-one default: do not adopt a full RAG app yet. Borrow patterns from Onyx and RAGFlow.**

Full platforms can teach us:

- connector UX.
- knowledge-base management.
- citations.
- admin settings.
- search/chat interaction patterns.

But adopting one as the core app would conflict with Sunshine’s custom review, taxonomy, placement, and no-lost-data requirements.

### Implementation Strategy

- Keep dashboard.
- Add search/RAG views after ingestion quality improves.
- Use Onyx/RAGFlow as benchmarks:
  - Can they index our processed artifacts?
  - Are citations better?
  - Is connector coverage useful?

### Success Criteria

- Users can search verified extracted content.
- Answers include citations to source files/chunks.
- Review status gates whether content is visible for final use.
- Unknown/low-quality docs do not pollute trusted search.

## Provider Evaluation Matrix

| Tool | Best Use | Integration Shape | Risk | Recommendation |
| --- | --- | --- | --- | --- |
| Docling | OCR, layout, tables, Markdown/JSON | Python provider inside extraction node | Confidence/page metadata may need mapping | First parser to integrate |
| MinerU | Advanced PDF/document parsing | Provider benchmark, maybe Python/CLI service | Heavier model/runtime requirements | Benchmark after Docling |
| RAGFlow DeepDoc | OCR/layout/chunking, full RAG platform | External parser benchmark/service | Full platform complexity | Benchmark, do not adopt wholesale |
| Unstructured | Broad file ETL/chunking | Python provider/chunker | OCR quality may be weaker than specialized parsers | Good fallback/general parser |
| Onyx | Connectors/search/RAG UX | Connector/source inspiration or external index | Full app overlap | Evaluate for connectors |
| LlamaIndex | Readers, node parsers, retrieval tools | Library components behind providers | Can sprawl quickly | Use selectively for connectors/chunking |
| Haystack | Modular RAG/retrieval/reranking pipelines | Retrieval/rerank experiment provider | Another pipeline abstraction | Use for retrieval experiments, not main graph |
| Dify | App/workflow reference | UX/reference only | Competes with our product | Do not integrate now |
| Langflow | Visual workflow reference | Prototype/reference only | Replaces code-owned graph if overused | Do not use as runtime |
| Qdrant | Vector/hybrid index | VectorStore provider | Additional service | Recommended vector store |
| OpenSearch | Lexical/hybrid search | Later search backend | Heavier ops | Add only if needed |
| Phoenix | RAG/LLM observability/evals | Eval/trace provider | Additional service | Evaluate later |
| Langfuse | LLM tracing/model usage | Already dependency | Needs disciplined instrumentation | Use now |
| Ragas/DeepEval | RAG answer evaluation | Eval provider | Less useful before answer generation | Add later |
| Airbyte | Data connectors/ELT | External sync layer | Heavy for file corpus | Only if SaaS connectors needed |

## Implementation Roadmap

### Milestone 1: Provider Boundary Cleanup

Goal:

- Make every major graph phase provider-addressable without changing graph topology.

Tasks:

- Add provider protocols:
  - `ExtractionProvider`
  - `ChunkProvider`
  - `EmbeddingProvider` already exists.
  - `VectorStoreProvider`
  - `RetrievalProvider`
  - `RerankProvider`
  - `LLMProvider`/`LLMInspector`
  - `ConnectorProvider`
- Add provider config to run metadata.
- Add provider result normalization.

Success:

- Current behavior still passes tests.
- Providers can be mocked in node tests.
- Run report shows provider names per phase.

### Milestone 2: Parser/OCR Benchmark

Goal:

- Stop guessing about OCR/parser quality.

Providers:

- current.
- Docling.
- MinerU.
- RAGFlow DeepDoc.
- Unstructured.

Success:

- Dashboard comparison shows per-file text snippets, quality, warnings, runtime, cost, and route status.
- We can choose a default parser by evidence.

### Milestone 3: Structure-Aware Chunking Benchmark

Goal:

- Improve retrieval and tag accuracy by preserving structure.

Providers:

- current chunker.
- Docling-derived chunks.
- Unstructured chunks.
- LlamaIndex markdown/node parser.

Success:

- Better golden-label retrieval top-k.
- Table/scrapbook/news clipping chunks are inspectable.
- Chunk count remains bounded.

### Milestone 4: Vector/Retrieval Stack

Goal:

- Replace ad hoc semantic retrieval with a production provider.

Recommended:

- Qdrant + Cortex embeddings + Cortex reranker.

Success:

- Golden-label semantic retrieval improves.
- Search supports filters and citations.
- Re-indexing is repeatable.

### Milestone 5: Observability And Eval

Goal:

- Make provider changes measurable and safe.

Recommended:

- Langfuse first.
- Phoenix/Ragas/DeepEval later for RAG Q&A.

Success:

- Every model call has trace/cost/runtime.
- Every provider benchmark has eval output.
- CI can run lightweight provider-interface tests.

### Milestone 6: Temporal Production Execution

Goal:

- Make batch runs durable.

Recommended:

- Temporal wraps batch orchestration.
- LangGraph remains single-file intelligence graph.

Success:

- Batch can resume after worker restart.
- Cancellation is reliable.
- Per-file progress is durable.

## What We Should Not Do

- Do not replace LangGraph with RAGFlow, Dify, Langflow, or Haystack.
- Do not replace the dashboard before review workflow stabilizes.
- Do not add five provider frameworks at once.
- Do not make external APIs implicit.
- Do not accept provider confidence without our validation gate.
- Do not over-engineer file loading, content identity, routing, or review decisions.

## Near-Term Recommendation

The best next slice is:

```text
Provider benchmark framework:
  current OCR/extraction
  Docling
  MinerU
  RAGFlow DeepDoc
  Unstructured
```

This gives us real evidence for the biggest current weakness: document parsing/OCR quality. After that, evaluate chunking and retrieval providers using the improved parser output.

## References

- LangGraph: https://github.com/langchain-ai/langgraph
- Temporal: https://github.com/temporalio/sdk-python
- Docling: https://github.com/docling-project/docling
- RAGFlow: https://github.com/infiniflow/ragflow
- MinerU: https://github.com/opendatalab/MinerU
- Unstructured: https://github.com/Unstructured-IO/unstructured
- Onyx: https://github.com/onyx-dot-app/onyx
- LlamaIndex: https://github.com/run-llama/llama_index
- LlamaHub: https://github.com/run-llama/llama-hub
- Haystack: https://github.com/deepset-ai/haystack
- Dify: https://github.com/langgenius/dify
- Langflow: https://github.com/langflow-ai/langflow
- Qdrant: https://github.com/qdrant/qdrant
- LanceDB: https://github.com/lancedb/lancedb
- OpenSearch: https://github.com/opensearch-project/OpenSearch
- Arize Phoenix: https://github.com/Arize-ai/phoenix
- Langfuse: https://github.com/langfuse/langfuse
- Ragas: https://github.com/explodinggradients/ragas
- DeepEval: https://github.com/confident-ai/deepeval
- Airbyte: https://github.com/airbytehq/airbyte
