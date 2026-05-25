# Sunshine Club

Sunshine Club is a Google Drive intelligence and organization system.

Its job is to:

- classify messy documents into a controlled tag system
- route files into canonical Google Drive folders
- stage low-confidence and duplicate cases for review
- keep new uploads organized over time
- power search, related discovery, and grounded chat on top

Google Drive is the production source of truth for organized files.

Phase 1 works from the Atlas VM NAS mount at `/mnt/sunshine`. See
`docs/corpus-inventory.md` for the current source groups, file types, and
pipeline implications.

The current taxonomy source of truth is the Verdify handoff and seed files in
`docs/`, summarized in `docs/taxonomy.md`.

The documentation lives in `docs/`.
