# Sunshine Taxonomy

Last aligned: 2026-05-25.

## Source of Truth

For V1 planning, the Verdify taxonomy handoff is the taxonomy source of truth:

- `docs/Sunshine_Verdify_Taxonomy_Tagging_Handoff_2026-05-25.md`
- `docs/Sunshine_Taxonomy_Seed_v0.1_2026-05-25.json`
- `docs/Sunshine_Taxonomy_v0.1_Workbook_2026-05-25.xlsx`

The handoff rule is authoritative:

- folders answer where a human volunteer expects a file to live
- the primary routing tag answers which single folder family the system routes toward
- secondary facets answer what the file is, what it concerns, where it came from, who may see it, what review it needs, and what outputs may use it

Sunshine Club should keep one primary routing tag per routed file, but secondary metadata must be faceted. Do not collapse record type, program, source collection, privacy, processing status, usage, and reviewer role into one flat pile of secondary tags.

## Canonical Folder Families

These top-level Google Drive folders are manually created and intentionally broad:

| Folder key | Drive folder | Default privacy |
|---|---|---|
| `00_read_me_runbooks` | `00_READ_ME_AND_RUNBOOKS` | `club_internal` |
| `01_governance_admin` | `01_Governance_Admin` | `board_only` |
| `02_finance_donations` | `02_Finance_Donations` | `treasurer_only` |
| `03_membership` | `03_Membership` | `member_private` |
| `04_programs_partnerships` | `04_Programs_Partnerships` | `club_internal` |
| `05_events` | `05_Events` | `club_internal` |
| `06_history_archive` | `06_History_Archive` | `club_internal` |
| `07_communications` | `07_Communications` | `club_internal` |
| `08_operations_assets` | `08_Operations_Assets` | `club_internal` |
| `09_125th_anniversary` | `09_125th_Anniversary` | `club_internal` |
| `90_intake_needs_review` | `90_Intake_Needs_Review` | `restricted` |
| `99_system_exports_logs` | `99_System_Exports_Logs` | `system_admin` |

## Primary Routing Tags

These primary tags route to the folder families above. Many primary tags intentionally map to the same top-level folder.

| Primary tag | Folder key | Placement rule | Default privacy |
|---|---|---|---|
| `runbooks_handoff` | `00_read_me_runbooks` | `flat` | `club_internal` |
| `governance_bylaws_policy` | `01_governance_admin` | `flat` | `board_only` |
| `meeting_records` | `01_governance_admin` | `by_year` | `club_internal` |
| `finance_treasurer_records` | `02_finance_donations` | `by_year` | `treasurer_only` |
| `donations_receipts_fundraising` | `02_finance_donations` | `by_year` | `donor_sensitive` |
| `membership_rosters_yearbooks` | `03_membership` | `by_year` | `member_private` |
| `dental_program` | `04_programs_partnerships` | `by_year` | `club_internal` |
| `senior_smiles` | `04_programs_partnerships` | `by_year` | `club_internal` |
| `scholarships` | `04_programs_partnerships` | `by_year` | `beneficiary_sensitive` |
| `partner_programs` | `04_programs_partnerships` | `by_year` | `club_internal` |
| `annual_spring_tea` | `05_events` | `by_year` | `club_internal` |
| `other_events` | `05_events` | `by_year` | `club_internal` |
| `history_archive_general` | `06_history_archive` | `by_year` | `club_internal` |
| `scrapbooks` | `06_history_archive` | `by_year` | `club_internal` |
| `historical_photos` | `06_history_archive` | `by_year` | `club_internal` |
| `press_publications` | `06_history_archive` | `by_year` | `public` |
| `communications_templates` | `07_communications` | `flat` | `club_internal` |
| `website_public_materials` | `07_communications` | `flat` | `public` |
| `operations_assets` | `08_operations_assets` | `flat` | `club_internal` |
| `legal_insurance_compliance` | `08_operations_assets` | `by_year` | `legal_irs_sensitive` |
| `anniversary_125th` | `09_125th_anniversary` | `flat` | `club_internal` |
| `cookbook_project` | `09_125th_anniversary` | `flat` | `club_internal` |
| `documentary_project` | `09_125th_anniversary` | `flat` | `club_internal` |
| `central_garden_project` | `09_125th_anniversary` | `flat` | `club_internal` |
| `system_exports_logs` | `99_system_exports_logs` | `by_year_month` | `system_admin` |

## Required Secondary Facets

Supported V1 secondary facet groups:

- `record_type`
- `function`
- `program_project_event`
- `source_collection`
- `privacy_access`
- `processing_status`
- `usage`
- `reviewer_role`

Privacy/access is policy metadata, not merely a search tag. Records marked `donor_sensitive`, `member_private`, `beneficiary_sensitive`, `legal_irs_sensitive`, `treasurer_only`, `system_admin`, or unresolved `restricted` must be excluded from normal search/chat unless the requesting user and workflow are allowed.

Processing status is also operational metadata. Files that need privacy review, date confirmation, person identification, source verification, publication approval, or duplicate review should not become trusted routing or chat sources until resolved.

## Implementation Implications

V1 should seed the taxonomy from `docs/Sunshine_Taxonomy_Seed_v0.1_2026-05-25.json` rather than relying on manual re-entry from prose.

The data model should support:

- stable tag keys and display names
- `tag_kind` for primary vs secondary
- `facet` or `tag_group` for secondary facets
- default privacy and reviewer role on primary tags
- first-class document privacy/access, processing status, usage, reviewer role, source collection, date value, and date confidence
- review task types for `privacy_review`, `date_confirmation`, `person_identification`, `source_verification`, `publication_approval`, and `family_return_review`
- acceptance tests based on the handoff retrieval questions and golden examples

The repo remains Track A from the handoff: archive and Google Drive intelligence. Donor CRM, receipt automation, governance survey operations, and anniversary project management are adjacent Track B/C decisions unless explicitly brought into this product.
