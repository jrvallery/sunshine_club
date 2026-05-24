# Sunshine Club Roadmap

## Delivery Principle

Build the intelligence and control loop first.

Do not start with a polished chat demo.

## Phase 1: Foundation

Build:

- monorepo skeleton
- database and migrations
- dashboard shell
- API shell
- worker shell
- connector interfaces

Exit criteria:

- apps boot locally
- migrations run
- baseline contracts exist
- the NAS `sunshineclub` working corpus is defined as the Phase 1 source root

## Phase 2: Extraction and Classification Core

Build:

- NAS `sunshineclub` source connector
- extraction pipeline
- chunking and embeddings
- classifier outputs
- candidate tag scoring and explanations

Exit criteria:

- sample files from the unified NAS `sunshineclub` corpus can be processed end to end
- classifier outputs top candidates and margin

## Phase 3: Tag and Placement Control Layer

Build:

- tags
- folders
- tag-to-folder mappings
- placement rules
- deterministic path resolution

Exit criteria:

- a primary tag plus metadata resolves to a deterministic destination path

## Phase 4: Review System

Build:

- low-confidence queue
- duplicate queue
- ignore flow
- new-tag creation flow
- misfiled-file queue

Exit criteria:

- human can resolve any non-auto-routable item through the dashboard

## Phase 5: Drive Action Engine

Build:

- action queue
- move actions
- staged import actions
- rollback support
- mapping migration batches

Exit criteria:

- semantic assignment and physical movement are tracked separately
- failed moves are recoverable

## Phase 6: Historical Cleanup

Build:

- organized import plan for material staged from the NAS `sunshineclub` corpus into Drive
- possible misfiled detection
- review-driven move proposals

Exit criteria:

- staged corpus can be imported into Drive with controlled placement decisions

## Phase 7: NAS Migration

Build:

- staged NAS inventory
- import validation against the target Drive structure
- import batches into Drive
- canonicalization rules

Exit criteria:

- staged local corpus can be safely imported into Drive
- original copies are retained during MVP

## Phase 8: Intake and Ongoing Auto-Routing

Build:

- dashboard upload flow
- universal intake folder lifecycle
- processing statuses
- high-confidence auto-routing

Exit criteria:

- new files can flow from upload to intake to final destination

## Phase 9: Search and Chat

Build:

- semantic search
- tag filtering
- related files
- grounded chat
- explanation surfaces

Exit criteria:

- users can find and understand files without browsing Drive directly

## Phase 10: Learning and Tuning

Build:

- review decision capture
- bounded learning loop
- threshold tuning
- observability and routing metrics

Exit criteria:

- review burden trends downward
- routing quality improves over time without uncontrolled drift
