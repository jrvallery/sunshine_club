# File Segmentation Design

## Purpose

Sunshine Club has many long scanned PDFs and image packets that are not one clean document. A single source file may contain scrapbook pages, newspaper clippings, meeting packets, financial tables, handwritten notes, and historical summaries. The pipeline needs to make those internal document boundaries visible without risking data loss.

The segmentation system will represent those boundaries as reviewed logical page-range segments first. The original source file remains immutable. Physical child-file export is a later explicit action after segment boundaries have been reviewed and benchmarked.

## Goals

- Preserve every original file exactly as received.
- Detect likely child documents inside long PDFs and scanned packets.
- Store proposed segments as database records with parent-file provenance, page ranges, evidence, extracted text, and review status.
- Let reviewers accept, reject, merge, split, or rename proposed segments.
- Make search and retrieval return the relevant page-range segment, not only the parent file.
- Retag accepted or proposed segments independently from the parent file when useful.
- Turn accepted segment decisions into golden segment labels for future segmentation benchmarks.
- Keep LangGraph deterministic and auditable: providers supply evidence, but the graph owns the final segmentation decision.

## Non-Goals

- Do not delete, rewrite, or move source files during automated processing.
- Do not automatically create permanent child PDFs from unreviewed segment proposals.
- Do not let Docling, an LLM, or any parser silently define final archive boundaries.
- Do not require perfect segmentation before OCR, tagging, or review can proceed.

## Current State

Implemented today:

- `propose_document_segments` exists in the V2 graph after extraction quality checks and structure normalization.
- Segment proposals are written to `sample-document-segments.jsonl`.
- Review-required segment proposals are written to `sample-review-queue.jsonl`.
- Segment-aware review rows can now be imported into the Review tab without collapsing multiple segments from the same parent file.
- Segment review rows use distinct internal storage keys while displaying the real original source path.
- The parent source file remains unchanged.

Current limitation:

- Segmentation is mostly page-range based.
- Splitting multiple articles inside one scanned page is not yet reliable.
- Segment-level tagging exists partially through segment-aware chunks, but the next milestone should make segment-level tag decisions first-class.

## Architecture

### Pipeline Position

```text
load_file_context
-> identify_file
-> probe_file
-> classify_content_type
-> plan_extraction
-> select_extraction_provider
-> extract_content
-> validate_extraction
-> repair_or_escalate_extraction
-> quality_gate
-> normalize_document_structure
-> propose_document_segments
-> chunk_content
-> embed_chunks
-> index_chunks
-> retrieve_labeled_examples
-> assign tags
-> route/review
-> persist/import
```

Segmentation happens after extraction because it needs page text, OCR quality, layout structure, and provider evidence. It happens before chunking so chunks, embeddings, retrieval matches, and tags can attach to the correct segment.

### Source of Truth

The source file is always the canonical record.

Segments are logical child-document records:

```text
parent file: /mnt/sunshine/.../Adobe Scan Mar 24, 2026.pdf
segment: pages 1-10
segment: pages 11-20
segment: pages 21-30
```

The database stores the segment. The original file is not split by default.

## Data Model

### `document_segments`

Each segment row should include:

- `segment_id`
- `parent_file_id`
- `run_id`
- `run_key`
- `source_path`
- `relative_path`
- `parent_content_sha256`
- `page_start`
- `page_end`
- `segment_index`
- `segment_type`
- `segment_title`
- `segment_confidence`
- `segment_boundary_evidence`
- `requires_segment_review`
- `review_status`
- `review_decision`
- `reviewer`
- `review_notes`
- `accepted_at`
- `created_at`
- `updated_at`

Segment metadata should include:

- extraction provider
- OCR provider
- OCR quality
- text length
- text snippet
- layout evidence
- source parser evidence
- parent modified timestamp and size

### `review_items`

Segment review items should point to the original source file but use a unique internal storage key:

```text
review_storage_source_path =
  {source_path}#segment={segment_id}
```

The API should still return:

```text
source_path = original parent source path
result.segment_id = segment id
result.page_start = page start
result.page_end = page end
```

This lets the UI show multiple review rows for one parent file.

### `chunks`

Segment-aware chunks should include:

- `chunk_id`
- `segment_id`
- `parent_segment_id`
- `source_path`
- `page_start`
- `page_end`
- `chunk_kind`
- `text`
- `metadata.segment_title`
- `metadata.segment_type`

For search, chunks are the retrieval unit. The search result should cite the segment and parent file.

## Segmentation Decision Policy

The segmenter should be conservative. False splits are more dangerous than missed splits because false splits can make one coherent document look like several unrelated records.

### Inputs

- Page count.
- OCR page text.
- OCR quality by page.
- Normalized Docling/page/layout structure.
- Tables, headings, image blocks, captions, and text provenance.
- File path/name signals such as `scrapbook`, `newspaper`, `ledger`, `minutes`, `budget`.
- Blank or low-text separator pages.
- Page topic shifts.
- Continuation language such as `continued`, `continued on`, or `continued from`.
- Golden segment labels from prior reviewed runs.

### Initial Segment Types

- `single_document`
- `scrapbook_page`
- `scrapbook_page_group`
- `newspaper_article`
- `newspaper_article_group`
- `meeting_packet_section`
- `financial_packet_section`
- `historical_context_section`
- `mixed_collection_page`
- `mixed_collection_page_group`
- `unknown_page_group`

### Page-Range Grouping Rules

1. If the file appears to be one normal document, emit one `single_document` segment.
2. If the file is a multi-page scrapbook, newspaper, or mixed packet, emit review-required page-range proposals.
3. If blank/separator pages exist, group pages between separators.
4. If consecutive pages have similar topics, group them together.
5. If the file is very large and no reliable boundaries exist, emit fixed review windows rather than pretending the boundaries are final.
6. If multiple articles exist on one page, keep the page as one segment until layout-level evidence is strong enough to propose intra-page regions.

## Provider Role

### Docling

Docling should be used as a structure/evidence provider, not as the final authority.

Useful Docling outputs:

- page text
- page numbers
- layout blocks
- tables
- headings
- image references
- provenance from text items back to pages

The pipeline should normalize Docling output into provider-neutral structure rows, then pass those rows into `propose_document_segments`.

### OCR Providers

OCR providers supply page text and confidence. They do not decide archival boundaries.

Local-first priority:

1. Current local OCR / Docling where usable.
2. Cortex or local model fallback where configured.
3. No third-party API calls for production customer data unless explicitly allowed by policy.

### LLM Role

LLMs may help with:

- suggested segment title
- short segment summary
- detecting likely continuation across pages
- suggesting merge/split review actions

LLMs must not:

- silently accept final segment boundaries
- physically split files
- override reviewed golden segment labels

## Review Workflow

### Proposed Segment Review

The dashboard should show:

- parent file name/path
- page range
- segment type
- proposed title
- OCR/layout text snippet
- boundary evidence
- confidence
- current tag proposal
- preview link opening parent file at the relevant page range when possible

Reviewer actions:

- `accept`: proposed page range is correct.
- `reject`: proposed segment should not exist.
- `split`: range contains multiple child documents.
- `merge`: range should be combined with neighboring segment.
- `rename`: title should change.
- `retag`: primary/secondary tags should change.
- `defer`: needs later technical or domain review.

### Golden Segment Labels

Accepted or corrected segment decisions should create golden labels:

- parent file
- accepted page range
- corrected segment type
- corrected title
- corrected primary tag
- corrected secondary tags
- notes
- reviewer

Golden segment labels become the benchmark set for future segmentation changes.

## Segment Naming

### Temporary Display Name

Before review:

```text
{parent_filename} p{page}
{parent_filename} pp{start}-{end}
```

Example:

```text
Adobe Scan Mar 24, 2026.pdf pp21-30
```

### Reviewed Segment Title

After review, title should be human-meaningful:

```text
1992-1993 Meeting Minutes Packet pp1-33
Small Green Scrapbook Newspaper Clippings pp11-20
Sunshine Tea Guest List 2007 pp1-10
```

### Future Export Filename

Physical export is later and review-gated:

```text
{parent_slug}__p{start}-p{end}__{primary_tag}__{reviewed_title_slug}.pdf
```

Example:

```text
Adobe_Scan_Mar_24_2026__p021-p030__scrapbooks__small_green_clippings.pdf
```

Exported child files must include metadata linking back to:

- parent source path
- parent content hash
- segment ID
- reviewed decision ID
- page range
- export timestamp
- exported file hash

## Retagging Behavior

Segment-level tagging should be first-class.

Parent file:

- Represents the container.
- May be tagged as `scrapbooks`, `meeting_packet`, `financial_packet`, or `mixed_collection`.

Child segment:

- Gets its own primary tag and secondary tags.
- Uses only segment text/layout/chunks where possible.
- Retrieves similar golden examples using segment-level text.
- Can differ from parent tag.

Example:

```text
Parent: Adobe Scan Mar 24, 2026.pdf
Parent tag: scrapbooks

Segment pp1-10:
  tag: press_publications

Segment pp11-20:
  tag: historical_photos

Segment pp21-30:
  tag: meeting_records
```

This prevents one large scrapbook packet from forcing every child item into the same tag.

## Search Behavior

Search should return segment-aware results:

```text
Title: Adobe Scan Mar 24, 2026.pdf pp21-30
Parent: Adobe Scan Mar 24, 2026.pdf
Segment type: scrapbook_page_group
Primary tag: meeting_records
Pages: 21-30
Snippet: ...
Open: parent PDF at page 21
```

Search filters should support:

- parent file
- run
- primary tag
- secondary tag
- segment type
- segment review status
- OCR quality
- page range

## Implementation Plan

### Milestone 1: Durable Segment Review

- Ensure all successful dashboard runs auto-import review items.
- Ensure every review-required segment appears as a Review tab row.
- Store segment ID, page range, segment type, and evidence in the review item result JSON.
- Preserve the original source path in API responses.
- Use segment-aware internal storage keys to avoid row collapse.

Success criteria:

- A run with 7 proposed segments from the same PDF creates 7 Review tab rows.
- Clicking each row opens a distinct review item.
- No source file is modified.

### Milestone 2: Segment Review UI

- Add page range and segment type columns to Review tab.
- Add segment preview panel in Review detail.
- Add accept/reject/split/merge/rename actions.
- Show boundary evidence and OCR snippet.

Success criteria:

- Reviewer can resolve segment rows without looking at raw JSON.
- Segment decisions persist and are visible in the run report.
- Segment rows can be filtered by `review_segment_boundary`.

### Milestone 3: Segment-Level Tagging

- Treat each accepted/proposed segment as a virtual document for tagging.
- Use segment text and segment chunks for embeddings and nearest-label retrieval.
- Store segment-level primary and secondary tags.
- Display parent tag separately from segment tag.

Success criteria:

- One parent PDF can have multiple segment tags.
- Search returns segment-level tag evidence.
- Segment tag accuracy can be measured against golden segment labels.

### Milestone 4: Provider Benchmarking

- Benchmark current OCR, Docling, and other local parsers on known packet samples.
- Measure page text quality and segmentation-readiness.
- Compare boundary precision and recall against golden segment labels.

Success criteria:

- Benchmark includes scrapbook packets, newspaper packets, meeting packets, financial packets, and normal no-split PDFs.
- Provider report identifies whether Docling improves segmentation evidence enough to promote.
- No provider can be promoted if it loses page provenance.

### Milestone 5: Reviewed Physical Export

- Add export action for accepted segments only.
- Generate child PDFs or derivative files from reviewed page ranges.
- Store export metadata and artifact hash.
- Keep parent file unchanged.

Success criteria:

- Exporting a segment is deterministic and repeatable.
- Exported file can always be traced back to the parent source file and reviewed decision.
- Rejecting or changing a segment never deletes the parent or prior audit record.

## Success Criteria

The segmentation system is successful when:

- Long packet files produce inspectable page-range proposals.
- Every review-required segment appears in the Review tab automatically after run completion.
- Multiple segments from the same source file are not collapsed.
- Segment search returns page ranges, snippets, parent file links, and tags.
- Human decisions create reusable golden segment labels.
- Benchmark metrics show boundary precision, boundary recall, false split rate, and missed split rate.
- Physical splitting remains disabled until reviewed decisions and benchmark thresholds justify it.

Target benchmark gates before automatic segment acceptance:

- False split rate below 2% on golden packet set.
- Boundary precision at or above 95%.
- Boundary recall at or above 85%.
- 100% parent provenance preservation.
- 0 source-file mutations during automated processing.

## Open Questions

- Should segment review decisions live only in Postgres V2, or should SQLite legacy review continue to support them until migration is complete?
- What is the first golden segment benchmark set: 25 segments, 50 segments, or 100 segments?
- Do we need page thumbnails in the first segment review UI, or is extracted text plus parent PDF preview enough?
- Which local parser should be promoted first for layout evidence: Docling, MinerU, RAGFlow DeepDoc, or current OCR plus heuristics?
- What confidence threshold should allow a segment to skip review after the golden benchmark exists?

## Recommended Next Step

Build Milestone 2 next: segment review UI. The backend can already persist segment rows. The immediate bottleneck is reviewer usability: page ranges, boundary evidence, and accept/split/merge actions need to be visible without opening raw JSON.
