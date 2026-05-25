# Sunshine Club Docs

This doc set replaces the earlier single-plan document.

Read in this order:

1. `product-spec.md`
2. `technical-architecture.md`
3. `workflows.md`
4. `technical-stack.md`
5. `taxonomy.md`
6. `corpus-inventory.md`
7. `corpus-taxonomy-report.md`
8. `data-model.md`
9. `roadmap.md`
10. `implementation-plan.md`

## Document Map

- `product-spec.md`
  - product goals
  - user roles
  - operating rules
  - canonical behavior decisions

- `technical-architecture.md`
  - system architecture
  - connectors
  - classification and routing design
  - service boundaries
  - safety rules

- `technical-stack.md`
  - chosen implementation stack
  - why each technology fits
  - where each technology sits in the system
  - acceptable alternatives and rejected baselines

- `corpus-inventory.md`
  - current `/mnt/sunshine` mount shape
  - source groups and manifests
  - observed file types and counts
  - extraction and routing implications

- `taxonomy.md`
  - Verdify taxonomy handoff alignment
  - canonical folder families
  - V1 primary routing tags
  - required secondary facet groups
  - privacy and review implications

- `taxonomy-handoff/`
  - preserved Verdify handoff markdown, seed JSON, workbook, and source briefs

- `corpus-taxonomy-report.md`
  - corpus survey evidence
  - taxonomy/folder recommendations aligned to the Verdify handoff
  - duplicate and ambiguity patterns

- `workflows.md`
  - Google Drive cleanup
  - NAS staging and migration
  - upload intake
  - review and action workflows
  - drift correction

- `data-model.md`
  - core entities
  - tag model
  - placement rules
  - action and review state

- `roadmap.md`
  - delivery phases
  - dependencies
  - exit criteria

- `implementation-plan.md`
  - implementation-ready phase plan
  - proposed monorepo structure
  - schema outline
  - FastAPI, LangGraph, Temporal, and Postgres boundaries
  - first thin slice
