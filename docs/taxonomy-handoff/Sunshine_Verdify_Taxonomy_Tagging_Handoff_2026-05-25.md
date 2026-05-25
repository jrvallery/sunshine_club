# Sunshine Verdify Taxonomy and Tagging Handoff

Prepared: 2026-05-25
Sources: Emily's two May 25 Slack handoff briefs, James's `jrvallery/sunshine_club` repo as cloned on 2026-05-25, Sunshine local archive structure under `/mnt/emily/Sunshine`, recent Paige memory/search context, and the May 22 Sunshine document intake manifest.

## Bottom Line

James should move forward with the repo as the *archive and Google Drive intelligence layer*, but the taxonomy needs to be defined as a controlled, faceted model before bulk ingestion.

Use this rule:

- *Folders* answer: where should a human volunteer expect this to live?
- *Primary routing tag* answers: what single folder family should the system route this file toward?
- *Secondary facets* answer: what is it, who/what is involved, where did it come from, who may see it, what still needs review, and what outputs can use it?

Do not build a deep folder tree like `History > 1930s > Dental > Rotary > Margaret Allen > Photos`. Sunshine records overlap too much for that. A scrapbook page can be dental history, Rotary history, a Margaret Allen source, a 125th anniversary source, and a Green Scrapbook source at the same time.

## Files Created

- `Sunshine_Taxonomy_v0.1_Workbook_2026-05-25.xlsx` - working workbook for Emily/James with folders, primary routing tags, secondary facets, golden examples, and James backlog.
- `Sunshine_Taxonomy_Seed_v0.1_2026-05-25.json` - engineer-friendly seed version of the same taxonomy.
- `source_briefs/Sunshine_Club_Verdify_Brief.docx` - preserved Slack upload.
- `source_briefs/chatgptsunshine_verdify_chat.docx` - preserved Slack upload.

## How This Fits James's Repo

James's current product spec expects exactly one primary tag for routed files, plus optional secondary tags. That is the right skeleton. The missing piece is that secondary tags need facets, not one flat pile.

Recommended repo mapping:

- Keep `document_tag_assignments.assignment_role = primary` for one routing tag.
- Use `assignment_role = secondary` for record type, program/project/event, entity mentions, source collection, privacy/access, processing status, usage, and reviewer role.
- Add `facet` or `tag_group` to the `tags` table so `Dental Program` as a primary routing tag is not confused with `Dental Program` as a program facet.
- Treat privacy/access as first-class policy metadata, not just a tag. Donor, member-private, beneficiary-sensitive, legal/IRS-sensitive, and treasurer-only records must be excluded from normal search/chat.
- Add date confidence fields. Archive dates will often be exact, inferred, approximate, range, or unknown.
- Add provenance fields. The NAS corpus is staging; Sunshine Google Drive should become the club-owned source of truth after reviewed import.

## Primary Routing Tags

Use a controlled set of primary tags that map to simple top-level Drive folders. The starter workbook includes tags such as:

- `runbooks_handoff`
- `governance_bylaws_policy`
- `meeting_records`
- `finance_treasurer_records`
- `donations_receipts_fundraising`
- `membership_rosters_yearbooks`
- `dental_program`
- `senior_smiles`
- `scholarships`
- `partner_programs`
- `annual_spring_tea`
- `history_archive_general`
- `scrapbooks`
- `historical_photos`
- `press_publications`
- `communications_templates`
- `operations_assets`
- `legal_insurance_compliance`
- `anniversary_125th`
- `cookbook_project`
- `documentary_project`
- `central_garden_project`
- `website_public_materials`
- `system_exports_logs`

The primary tag is not the whole meaning of the file. It is the routing decision.

## Canonical Folder Families

Keep Drive boring:

```text
00_READ_ME_AND_RUNBOOKS
01_Governance_Admin
02_Finance_Donations
03_Membership
04_Programs_Partnerships
05_Events
06_History_Archive
07_Communications
08_Operations_Assets
09_125th_Anniversary
90_Intake_Needs_Review
99_System_Exports_Logs
```

Most intelligence should live in metadata/tags/search, not nested folders.

## Required Secondary Facets

At minimum, James should support these secondary facets:

- `record_type` - photo, scrapbook_page, yearbook_scan, meeting_minutes, agenda, treasurer_report, donation_export, event_material, governance_document, membership_record, press_clipping, presentation, inventory, publication, research_note, legal_insurance, email_correspondence, web_asset, dataset_workbook, runbook.
- `function` - governance, finance, donations_fundraising, membership, programs_mission, events, communications, history_archive, operations_assets, public_relations, anniversary_projects.
- `program_project_event` - Annual Spring Tea, Dental Program, Senior Smiles, Scholarships, Atwood House, Longmont Rotary Partnership, 125th Anniversary, Documentary, Cookbook, Central Garden, Insurance Project, Governance Survey, Stuart Funds Policy, PayPal Donation Infrastructure, Silver Service, History Book, Buddy Bench, etc.
- `source_collection` - Green Scrapbook, Black Chest Archive, Yearbooks, Yearbook Rescan, Tea Guest Books, Dental Clinic Photos, Rotary History Folder, Emperor Visit 1921, Markley Letter Collection, Treasurer / Finance Records, Website Public Materials, Slack Upload, Emily Local Files, NAS Working Corpus, Google Drive Current Folder, and related archive streams.
- `privacy_access` - public, club_internal, board_only, treasurer_only, donor_sensitive, member_private, beneficiary_sensitive, legal_irs_sensitive, family_return_sensitive, system_admin, restricted.
- `processing_status` - not_digitized, scanned_photographed, ocr_needed, ocr_complete, ai_cataloged, human_review_needed, duplicate_candidate, needs_date_confirmation, needs_person_identification, needs_privacy_review, needs_source_verification, ready_for_drive_import, ready_for_publication, archived_final.
- `usage` - anniversary_history_book, documentary, rotary_presentation, museum_event, tea_program, cookbook, website, governance_review, treasurer_reconciliation, donor_stewardship, member_roster_reset, public_fact_bank, training_runbook.
- `reviewer_role` - historian, treasurer, president_board, correspondence_secretary, tea_chair, program_owner, board_restricted, anniversary_lead, archive_committee, communications_owner, verdify_admin.

## Privacy Rules That Should Be Non-Negotiable

- Scholarship applications, dental recipient/student/senior/veteran records, donor exports, member contact data, insurance/compliance, and treasurer records should not be normal chat/search sources.
- Public outputs need publication approval, not just a high classifier score.
- If a file is uncertain, route it to `90_Intake_Needs_Review`; do not guess it into a public or member-visible area.

## Golden Sample Set

The workbook includes a 20-item starter golden sample set from actual Sunshine files. James should expand this to 50-100 hand-labeled examples before running a bulk pass. Include:

- scrapbook pages
- yearbook scans
- membership/status records
- agenda-only records
- treasurer and budget records
- donor/payment materials
- scholarship/private program records
- historical photos and public assets
- anniversary committee docs
- ambiguous/messy files

This gives James a testable target. If the classifier cannot label the golden set correctly, the taxonomy or classifier needs work before migration.

## Immediate Requests For James

1. Add a taxonomy seed loader from the JSON/workbook.
2. Add `facet`/`tag_group` to tags.
3. Add privacy/access enforcement to search/chat.
4. Add date confidence and provenance/source collection metadata.
5. Add review task types for privacy, date confirmation, person identification, source verification, publication approval, and family-return review.
6. Add reviewer-role routing.
7. Add acceptance tests based on the retrieval questions in the workbook.
8. Treat the NAS `sunshineclub/` folder as staging only; Google Drive remains the club-owned production source after reviewed import.

## Caution

Do not let this become just a prettier folder cleanup. Emily's actual need is an operating handoff: the next president, historian, treasurer, Tea chair, and correspondence secretary should be able to find, trust, and use the records without Emily or James as the hidden integration layer.
