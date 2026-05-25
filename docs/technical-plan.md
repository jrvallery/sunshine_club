# Sunshine Club Technical Plan

This file is now the entry point into the full Sunshine Club documentation set.

Read in this order:

1. `README.md`
2. `docs/README.md`
3. `docs/product-spec.md`
4. `docs/technical-architecture.md`
5. `docs/technical-stack.md`
6. `docs/workflows.md`
7. `docs/data-model.md`
8. `docs/roadmap.md`

## What Changed

The earlier single-plan document has been replaced by a full doc set because the architecture is now more specific than a generic Google Drive RAG app.

Current design highlights:

- Google Drive is the canonical production library
- Phase 1 uses a manually consolidated NAS `sunshineclub` folder as the working corpus
- tags live in the Sunshine Club DB, not in Drive
- the classifier assigns tag candidates, not folders directly
- primary tags determine top-level placement
- placement rules derive objective subfolders like year
- review and Drive action execution are separate systems
- NAS content is a staging and migration source during build-out
- search and chat sit on top of the semantic organization layer


## Stack Baseline

The selected implementation stack is documented in `docs/technical-stack.md`.
