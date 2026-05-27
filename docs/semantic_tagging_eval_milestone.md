# Semantic Tagging Evaluation Milestone

## Goal

Replace the current brittle tag assignment behavior with an auditable semantic
tagging loop based on human-labeled examples, embeddings, retrieval, structured
LLM judgment, and measured evaluation.

This milestone is about proving tag correctness before scaling the pipeline.
Extraction and OCR can be useful while tag assignment is still wrong. The next
step is to separate those concerns and make tagging measurable.

The system must stop treating keyword matches as final truth. Tags should be
proposals until they are backed by taxonomy definitions, retrieved examples,
model evidence, and evaluation results.

## Problem

The current tagger is not reliable enough.

Observed failure modes:

- Incidental words dominate the result, such as `Tea` causing a historical club
  summary to become `annual_spring_tea`.
- Paths and text snippets are interpreted too literally.
- Deterministic rules are useful guardrails but too shallow for archival
  records.
- LLM tagging is not yet grounded in trusted examples.
- Embeddings are produced for chunks, but they are not yet used as a reliable
  retrieval layer for classification decisions.
- Confidence scores currently describe pipeline agreement more than real-world
  correctness.

This cannot be fixed by adding more hard-coded rules. Each new rule handles one
example but creates another edge case.

## Product Outcome

The user should be able to review a small set of files, label the correct
primary and secondary tags, and then see whether the pipeline can reproduce
those labels.

For each file, the system should show:

- extracted text snippet
- proposed primary tag
- proposed secondary tags
- confidence
- evidence
- nearest labeled examples used
- whether the prediction matched the human label
- reason for review when it did not match or confidence was not strong enough

The product should answer:

```text
Can we trust this tagger yet?
If not, which categories are confused and why?
```

## Architecture

### High-Level Flow

```text
extraction / OCR
  -> text validation
  -> chunking
  -> embeddings
  -> retrieve similar labeled examples
  -> structured LLM tag judgment
  -> confidence calibration
  -> route candidate or review
  -> evaluation report
```

### LangGraph Node Shape

The production graph should evolve toward this shape:

```text
START
  -> load_file_context
  -> classify_content_type
  -> plan_extraction
  -> extract_content
  -> validate_text_extraction
  -> quality_gate
  -> chunk_content
  -> embed_chunks
  -> retrieve_labeled_examples
  -> inspect_tags_with_llm
  -> calibrate_tag_confidence
  -> resolve_route_or_review
  -> persist_outputs
END
```

`assign_deterministic_tags` should become a guardrail/helper, not the core
classification authority.

### Golden Label Store

Create a durable labeled-example table or JSONL artifact.

Minimum fields:

```text
source_path
relative_path
sample_path
extracted_text_snippet
correct_primary_tag
correct_secondary_tags
reviewer
reviewed_at
notes
```

Optional but useful fields:

```text
document_type
ocr_quality
source_collection
date_hint
privacy_notes
```

The review dashboard should be the UI for creating and editing these labels.

### Embedding Index

Build an index over the golden labels and, later, over accepted corpus results.

Each labeled example should embed:

- normalized extracted text
- file path context
- human notes
- correct tag labels

Retrieval should return the top similar labeled examples with:

```text
label_source_path
correct_primary_tag
correct_secondary_tags
similarity_score
text_snippet
reviewer_notes
```

The first target can be a simple local SQLite table with stored vectors or a
JSONL vector cache. We can move to a vector database later if needed.

### Tagging Prompt

The LLM should receive:

- taxonomy definitions
- extracted text snippet and path
- content class and extraction quality
- nearest labeled examples
- deterministic guardrail signals

The model should return structured JSON:

```json
{
  "primary_tag": "history_archive_general",
  "secondary_tags": ["history_archive", "programs_mission"],
  "confidence": 0.82,
  "evidence": [
    "Text describes founders and club origin",
    "Nearest labeled examples are historical summaries"
  ],
  "competing_tags": [
    {
      "tag": "membership_rosters_yearbooks",
      "reason": "Yearbook path, but content is not a roster"
    }
  ],
  "needs_review": false,
  "rationale": "The file is a historical club summary, not an event-specific Tea record."
}
```

### Confidence Calibration

Confidence should not be a model self-report alone.

High confidence requires:

- LLM primary tag is valid taxonomy value
- nearest labeled examples mostly agree
- evidence references actual text/path facts
- no close competing tag
- extraction quality is acceptable

Review should be required when:

- extraction quality is poor or empty
- nearest examples disagree
- LLM and deterministic guardrails disagree strongly
- confidence is below threshold
- competing tag is plausible
- file is in a sensitive domain such as finance, donor, beneficiary, or member
  private records

## Implementation Plan

### Phase 1: Label Capture

Add dashboard support for human labels:

- `correct_primary_tag`
- `correct_secondary_tags`
- `decision`
- `notes`

Persist accepted labels into a golden-label artifact or SQLite table.

Deliverable:

```text
.local/sunshine-review.sqlite
golden_labels table
```

### Phase 2: Embedding Index

Create a command to build an embedding index from golden labels.

Example:

```bash
.venv/bin/python -m sunshine_extraction.semantic_index \
  --labels .local/sunshine-review.sqlite \
  --output .local/sunshine-semantic-index.sqlite
```

Deliverable:

- index creation command
- index stats
- smoke test showing nearest examples for one file

### Phase 3: Retrieval Node

Add `retrieve_labeled_examples` to the LangGraph pipeline.

Input:

- chunks
- extracted text
- source path

Output:

- nearest labeled examples
- similarity scores

Deliverable:

- graph audit event for retrieval
- result artifact showing examples used

### Phase 4: Retrieval-Assisted LLM Tagging

Update tag inspection so the LLM receives nearest examples and taxonomy
definitions.

Deliverable:

- structured prompt
- structured result
- competing tag field
- evidence field tied to text and examples

### Phase 5: Evaluation Report

Build a command that runs the tagger against golden labels and reports:

- primary tag accuracy
- secondary tag precision/recall
- confusion pairs
- review rate
- auto-accept precision
- files requiring manual review

Example:

```bash
.venv/bin/python -m sunshine_extraction.semantic_eval \
  --input-root "/mnt/sunshine/_manifest/.../qa samples" \
  --labels .local/sunshine-review.sqlite \
  --output-dir "/mnt/sunshine/_manifest/.../semantic-eval"
```

Deliverables:

```text
semantic-eval-summary.json
semantic-eval-results.jsonl
semantic-confusion-matrix.csv
semantic-review-required.csv
```

## Success Criteria

### Product Criteria

- User can label files in the dashboard without editing raw JSON.
- User can see which labeled examples influenced each proposed tag.
- User can inspect why a file was accepted or routed to review.
- Bad examples can be added to the golden set and improve future evaluation.

### Technical Criteria

- Tagging no longer depends primarily on keyword rules.
- Embeddings are used for retrieval of labeled examples.
- Every tag result records:
  - model/provider
  - nearest examples
  - evidence
  - confidence inputs
  - competing tags
- Deterministic rules are kept as guardrails only.
- Evaluation is repeatable from the command line.

### Quality Criteria

Before scaling beyond QA samples:

- Golden set contains at least 50 reviewed files.
- Each major confusing category has examples:
  - history archive vs yearbook
  - Tea event vs incidental Tea mention
  - scrapbook vs newspaper/press
  - finance vs meeting records
  - photo-only vs scanned document
- Primary tag auto-accept precision is at least 90% on the golden set.
- Any tag below threshold routes to review.
- No extraction or OCR failure is hidden by a high tag confidence score.

## Non-Goals

This milestone does not:

- move or delete source files
- reorganize Drive
- classify the entire corpus automatically
- solve entity extraction
- solve final user-facing search/chat
- replace OCR evaluation

It creates the evaluation and semantic tagging foundation needed before those
steps are safe.

## Open Decisions

- Storage: SQLite vector cache first, or a dedicated vector database?
- Model: Gemini embeddings only, or also local embeddings for privacy/cost?
- LLM tagger: Cortex by default, OpenAI fallback, or provider comparison?
- Dashboard: inline label editing now, or CSV import/export first?
- Thresholds: what auto-accept precision is acceptable for customer delivery?

## Recommended Next Step

Build Phase 1 and Phase 2 together:

1. Add golden-label fields to the review dashboard.
2. Let the user label the current QA rows.
3. Build a local embedding index over those labels.
4. Run one retrieval smoke test for known confusing examples.

That creates the data foundation needed to replace rule-heavy tagging with a
measurable semantic classifier.
