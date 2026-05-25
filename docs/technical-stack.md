# Sunshine Club Technical Stack

This document defines the core implementation stack for Sunshine Club.

It covers:

- the selected technologies
- why each one fits the product
- where each one sits in the architecture
- what alternatives were considered but not chosen as the baseline

## Stack Summary

The baseline stack for Sunshine Club is:

- `FastAPI`
- `LangGraph`
- `Postgres + pgvector`
- `Temporal`
- `OpenTelemetry + Langfuse`
- `Docling`
- `OCRmyPDF + Tesseract`
- optional `Marker`
- Sunshine Club-owned Postgres-backed audit, review, and action store
- Sunshine Club-owned runtime guards for loop detection, retry control, and budget enforcement

## Why This Stack Fits Sunshine Club

Sunshine Club is not just a chat app or a generic RAG demo.

It is a long-running document intelligence system that must:

- process a messy historical corpus
- classify and route files deterministically
- survive crashes and restarts
- pause for human review and resume later
- keep a durable record of what happened
- support search and grounded chat on top
- eventually control real write actions into Google Drive

Because of that, the stack needs to optimize for:

- durable workflow state
- deterministic control flow
- structured operational data
- strong observability
- reliable document extraction
- explicit safety controls

The framework layer alone does not solve those problems.

## Core Technology Choices

### FastAPI

FastAPI is the API layer.

Why it is the right choice:

- strong Python ergonomics
- mature async support
- clean fit for service boundaries and internal APIs
- excellent support for typed request and response models
- straightforward integration with background systems, tracing, and auth later
- easy to expose both admin and user-facing endpoints

Where it fits:

- dashboard backend APIs
- admin APIs
- upload intake endpoints
- search APIs
- chat APIs
- review and operations endpoints
- health and readiness endpoints

Role in the project:

- the main application interface for the dashboard and internal service surface

### LangGraph

LangGraph is the workflow and agent orchestration layer.

Why it is the right choice:

- good fit for graph-shaped workflows instead of free-form agent loops
- supports durable checkpoints and resumable state patterns
- supports human-in-the-loop pauses and resumes
- strong fit for classification, review, routing, and retrieval flows
- safer for this project than building a loose swarm of agents

Where it fits:

- classification workflow
- review-interrupt workflow
- retrieval and grounded chat workflow
- later operations workflows

Role in the project:

- orchestrates the decision flow between extraction, classification, review, and downstream actions

Important architectural note:

- Sunshine Club should use LangGraph mostly for controlled workflows, not for a many-agent swarm model

### Postgres + pgvector

Postgres is the system-of-record database.

`pgvector` is the vector retrieval extension inside that database.

Why it is the right choice:

- one durable relational store for operational truth
- strong fit for tags, folder mappings, actions, reviews, duplicates, and audit events
- vector search stays close to the rest of the data model
- simpler operationally than splitting structured and vector state across multiple databases too early
- works well for hybrid retrieval patterns

Where it fits:

- canonical document records
- extracted document metadata
- tag definitions
- tag-to-folder mappings
- placement rules
- review tasks
- action queues and action results
- duplicate relationships
- audit events
- embedding storage and vector search
- later learning signals from review outcomes

Role in the project:

- the primary persistent memory and operational truth layer

Important architectural note:

- Sunshine Club should not depend on a separate memory product as its core state system in V1
- structured application state belongs in Postgres first

### Temporal

Temporal is the durable execution layer.

Why it is the right choice:

- built for long-running workflows that survive worker crashes and restarts
- strong fit for multi-step tasks that pause for human review
- durable retries, timeouts, and workflow history are first-class
- better fit than a simple queue for import batches, review waits, and long-lived actions
- reduces risk of lost work during large corpus processing or production intake

Where it fits:

- ingestion jobs
- classification jobs
- review wait states
- batch import workflows
- Drive action workflows
- mapping migration batches
- reconciliation workflows later

Role in the project:

- the crash-resistant runtime backbone for long-running work

Important architectural note:

- LangGraph manages flow logic
- Temporal manages durable execution and resumption semantics
- these layers solve different problems and should not be collapsed conceptually

### OpenTelemetry + Langfuse

OpenTelemetry is the telemetry standard.

Langfuse is the LLM and workflow observability product layer.

Why they are the right choice:

- Sunshine Club needs end-to-end traceability across ingestion, classification, review, search, and chat
- cost and latency visibility matter for agentic workflows
- prompt, model, and decision traces need to be inspectable later
- useful for debugging classification mistakes and audit questions
- strong support for observability without treating the framework itself as the logging layer

Where they fit:

- request tracing
- workflow tracing
- model call tracing
- cost tracking
- latency tracking
- prompt and response inspection
- evaluation later
- ops dashboards and debugging

Role in the project:

- the primary observability layer for AI and application runtime behavior

Important architectural note:

- the framework should not be assumed to provide sufficient observability by itself
- Sunshine Club needs explicit tracing and cost visibility from day one

### Docling

Docling is the primary document extraction and parsing layer.

Why it is the right choice:

- strong support for document-heavy pipelines
- good fit for turning mixed files into structured text-bearing outputs
- useful across PDFs, office-style files, and document-like images
- better aligned to this project than building parsing from scratch

Where it fits:

- Phase 1 NAS corpus extraction
- later Google Drive document extraction
- normalization into internal structured document objects
- text extraction for chunking, classification, and embedding

Role in the project:

- the main parser and extractor for document-like inputs

### OCRmyPDF + Tesseract

This is the OCR path for scanned and image-heavy PDFs, TIFFs, and document-like images.

Why it is the right choice:

- many real-world documents will be scans, receipts, or poor-quality PDFs
- OCR needs to be explicit, not assumed
- this stack is mature, widely used, and practical for a mixed corpus
- pairs well with a primary parser like Docling

Where it fits:

- scanned PDFs
- scanned TIFF/JPEG/PNG files
- receipts
- image-based reports
- poor-text-source legacy documents
- structured OCR artifacts with page/block/table output, quality signals, and warnings

Role in the project:

- the primary extraction path for `scanned_document`
- the enhancement layer that can upgrade image-like files into scanned documents when text/layout evidence is strong
- the evidence producer for classification and retrieval

Important architectural note:

- low-text photos are still generally outside normal semantic document routing
- OCR is for document-like image content, not arbitrary photo libraries
- OCR output does not decide final folders; Sunshine Club routing stays deterministic from tag, mapping, and placement rule

### Marker as Optional Parser Fallback / Benchmark

Marker is optional, not part of the required baseline.

Why it is included:

- useful as a parser fallback for hard cases
- useful for benchmarking extraction quality against Docling on the real corpus
- reduces lock-in to a single parser path

Where it fits:

- parser comparison runs
- extraction QA
- fallback extraction path for specific file classes if needed

Role in the project:

- an optional secondary parser, not the primary architecture anchor

## Sunshine Club-Owned Systems

Some of the most important production needs should remain Sunshine Club-owned rather than outsourced to a framework.

### Postgres-Backed Audit, Review, and Action Store

This is a first-class internal system.

Why it is the right choice:

- the project needs durable records of decisions, reviews, and Drive mutations
- review state is part of the product, not just background metadata
- Drive writes need clear audit trails and rollback visibility
- classification outputs, alternatives, and final human decisions need to be preserved for learning later

Where it fits:

- review queue
- duplicate queue
- misfiled-file queue
- action execution history
- mapping migration batches
- audit and provenance records

Role in the project:

- the product’s operational memory and accountability layer

### Runtime Guards for Loop Detection and Budgets

This is another first-class internal system.

Why it is the right choice:

- uncontrolled retries and loops are one of the main failure modes of production AI systems
- framework choice does not remove the need for hard runtime policies
- this project needs explicit limits around cost, retries, and repeated actions

Required controls:

- max workflow steps per run
- max repeated tool-call signature count
- token and cost budgets per run
- retry budgets per document and per batch
- dead-letter handling
- idempotency for Drive actions
- circuit breakers for ambiguous downstream failures
- admin kill switches for bad runs

Where it fits:

- LangGraph workflow execution
- Temporal activity and workflow boundaries
- model call wrappers
- Drive action execution path
- background ingestion and import batches

Role in the project:

- the safety layer that keeps the system from burning money or mutating Drive irresponsibly

## How the Stack Maps to the Product

### Phase 1: Local Build-Out on NAS

Source:

- manually consolidated NAS corpus at `/mnt/sunshine`

Stack usage:

- `Docling` extracts born-digital documents and office-like files
- `OCRmyPDF + Tesseract` handle scanned PDFs, TIFFs, and document-like images
- image metadata tooling handles photo-heavy event/member files before deciding whether OCR is useful
- `LangGraph` orchestrates extraction and classification flows
- `Temporal` runs durable batch jobs across the local corpus
- `Postgres + pgvector` stores files, embeddings, tags, mappings, reviews, and decisions
- `OpenTelemetry + Langfuse` traces extraction and classification behavior
- runtime guards prevent runaway batch processing

### Phase 2: Admin Review and Organization Validation

Stack usage:

- `FastAPI` powers review and admin endpoints
- `Postgres` stores review tasks and action state
- `LangGraph` powers review-aware routing decisions
- `Temporal` holds paused work while waiting for human review
- `Langfuse` helps inspect why a file was classified or routed a certain way

### Phase 3: Organized Import into Google Drive

Stack usage:

- `Temporal` manages long-running import and move workflows
- `Postgres` stores action records, idempotency keys, and outcomes
- runtime guards and audit logs protect against bad bulk actions
- `FastAPI` exposes migration controls and status views

### Phase 4: Production Intake and Ongoing Routing

Stack usage:

- `FastAPI` receives dashboard upload requests
- the file is written into Drive intake
- `Temporal` schedules ingestion and routing workflows
- `LangGraph` classifies and routes based on tag + placement rule
- `Postgres + pgvector` remains the semantic and operational truth layer
- `Langfuse` traces ongoing production model behavior and cost

### Phase 5: Search and Grounded Chat

Stack usage:

- `FastAPI` exposes search and chat APIs
- `pgvector` supports semantic retrieval
- `Postgres` supports tag filters, relationships, and citations
- `LangGraph` orchestrates grounded retrieval and answer generation
- `Langfuse` traces model calls and answer behavior

## Explicitly Rejected Baseline Choices

These are not banned forever, but they are not the initial architecture baseline.

### Dedicated Agent Memory Products as the Core State Layer

Examples:

- Mem0
- Letta
- Zep / Graphiti

Why not as the baseline:

- Sunshine Club’s core memory is structured operational data
- document state, reviews, actions, mappings, and audit history belong in the application database first
- adding a separate memory system too early increases complexity without solving the core product problem

### Multi-Agent Swarm Frameworks as the Core Architecture

Examples:

- CrewAI as the primary execution model
- AutoGen-style many-agent coordination as the base design

Why not as the baseline:

- the product is mainly a controlled workflow system, not a role-playing agent society
- deterministic review and routing matter more than agent personas
- extra agent coordination adds complexity, cost, and debugging burden

### Framework-Only Observability

Why not:

- orchestration frameworks are not full observability systems
- Sunshine Club needs explicit traces, costs, and auditability

### Parser Lock-In Without Comparison

Why not:

- real corpora are messy
- parser quality should be measured against the actual data
- keeping `Marker` available as an optional benchmark/fallback keeps the architecture pragmatic

## Acceptable Alternatives

These are acceptable substitutions if implementation constraints change.

- `Prefect` instead of `Temporal` if the ops burden of Temporal is too high
- `Arize Phoenix` instead of or alongside `Langfuse` if evaluation workflows become the priority
- `Unstructured` as a parser path if connector ecosystem or file coverage makes it more useful than Docling for specific sources

These are alternatives, not the default recommendation.

## Final Position

The stack is designed around a simple principle:

- `FastAPI` exposes the product
- `LangGraph` controls the decision flow
- `Temporal` keeps long-running work durable
- `Postgres + pgvector` stores the truth
- `OpenTelemetry + Langfuse` make the system observable
- `Docling` and OCR tools turn messy files into usable text
- Sunshine Club-owned audit and runtime controls make the system safe enough to operate

That is the right shape for a product that must both understand documents and safely act on them.
