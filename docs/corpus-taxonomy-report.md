# Sunshine Corpus Taxonomy Report

Last checked: 2026-05-25.

## Executive Summary

High-confidence recommendation: Sunshine Club V1 should use the Verdify taxonomy handoff as the current source of truth. That means broad, stable top-level Google Drive folders, a controlled set of specific primary routing tags that map into those folders, and faceted secondary metadata in the Sunshine Club database. The corpus evidence does not support a deep folder tree as the primary intelligence layer.

The observed corpus is heavily image and scan weighted. The full inventory manifest under `/mnt/sunshine/_manifest/2026-05-25T1205MDT-sunshine-inventory/` describes 31,910 rows, including 31,907 local files planned for copy and about 150.294 GiB. By extension, that manifest is dominated by `jpg` at 21,655 files / about 121.5 GiB, `jpeg` at 7,245 / about 13.0 GiB, and `tif` at 1,039 / about 11.8 GiB. The currently mounted `/mnt/sunshine` tree contains 9,224 actual files / about 44.9 GiB, also dominated by image-like files.

High-confidence folder recommendation:

1. `00_READ_ME_AND_RUNBOOKS`
2. `01_Governance_Admin`
3. `02_Finance_Donations`
4. `03_Membership`
5. `04_Programs_Partnerships`
6. `05_Events`
7. `06_History_Archive`
8. `07_Communications`
9. `08_Operations_Assets`
10. `09_125th_Anniversary`
11. `90_Intake_Needs_Review`
12. `99_System_Exports_Logs`

High-confidence V1 primary routing tags are the 25 tags from the Verdify seed, including `meeting_records`, `finance_treasurer_records`, `donations_receipts_fundraising`, `membership_rosters_yearbooks`, `dental_program`, `senior_smiles`, `scholarships`, `annual_spring_tea`, `scrapbooks`, `historical_photos`, `press_publications`, `anniversary_125th`, and `system_exports_logs`. Many of these map to the same broad top-level folder. Secondary facets then carry record type, function, program/project/event, source collection, privacy/access, processing status, usage, and reviewer role.

V1 should not force low-text photos through text-centric semantic routing. Photos, scanned pages, receipts, emails, spreadsheets, and workspace/manifests need content-class-specific extraction and routing behavior before semantic classification.

## Where I Looked

Primary repo documentation:

- `README.md`
- `docs/README.md`
- `docs/product-spec.md`
- `docs/technical-architecture.md`
- `docs/technical-stack.md`
- `docs/workflows.md`
- `docs/data-model.md`
- `docs/roadmap.md`
- `docs/technical-plan.md`
- existing `docs/corpus-inventory.md`

Mounted corpus and nearby source evidence:

- `/mnt/sunshine`
- `/mnt/sunshine/_manifest/2026-05-25T1205MDT-sunshine-inventory/`
- `/mnt/sunshine/Sunshine shared folders/`
- `/mnt/sunshine/From Mac Sunshine Pass 2026-05-25/`
- `/mnt/sunshine/Paige Agent Sunshine Files/`
- `/mnt/sunshine/google-drive-delta-2026-05-25/`
- `/mnt/sunshine/archive-2026-05-25/`
- `/mnt/atlas-vault`
- `/mnt/james/atlas-vault`
- nearby Paige/Sunshine working paths under `/mnt/agents/paige/`

Atlas vault finding: `/mnt/atlas-vault` and `/mnt/james/atlas-vault` each contain 45 files, mostly Obsidian markdown plus one `text_memory.sqlite` around 364.7 MB. Text search found no Sunshine hits in the readable files. I do not recommend treating Atlas vault as a normal Sunshine corpus source for V1, except as evidence that Obsidian/system sidecars may appear in mounted data.

Nearby Paige evidence is relevant. `/mnt/agents/paige/work/sunshine-consolidation-2026-05-25/` contains comparison, duplicate, NAS inventory, and Drive-focused inventory outputs. The Verdify handoff now preserved in `docs/` is treated as authoritative for taxonomy terms; this report grounds those terms in mounted corpus evidence.

## Corpus Inventory Summary

Manifested full corpus shape:

| Source group | Rows | Size |
|---|---:|---:|
| `canonical_nas_sunshine_root` | 23,517 | 109.595 GiB |
| `mac_import_sunshine_in_progress_and_google_drive_export` | 5,067 | 15.763 GiB |
| `microsoft_onedrive_backup_sunshine_root` | 2,019 | 22.046 GiB |
| `filename_or_content_match` | 486 | 1.253 GiB |
| `paige_context_content_match` | 477 | 0.122 GiB |
| `legacy_onedrive_fastfoto` | 298 | 1.500 GiB |
| `sunshine_dashboard_workbooks` | 43 | 0.015 GiB |
| `live_slack_sunshine_club` | 2 | metadata only |
| `gog_drive` | 1 | metadata only |

Manifested dominant file extensions:

| Extension | Count | Size |
|---|---:|---:|
| `jpg` | 21,655 | 121.482 GiB |
| `jpeg` | 7,245 | 12.964 GiB |
| `tif` | 1,039 | 11.833 GiB |
| `md` | 401 | 0.006 GiB |
| `txt` | 291 | 0.007 GiB |
| `docx` | 234 | 0.021 GiB |
| `eml` | 225 | 0.014 GiB |
| `pdf` | 224 | 3.341 GiB |
| `xlsx` | 175 | 0.011 GiB |
| `png` | 152 | 0.302 GiB |
| `json` | 59 | 0.017 GiB |
| `py` | 57 | very small |
| `csv` | 30 | 0.052 GiB |
| `pub` | 12 | 0.141 GiB |
| `pptx` | 9 | 0.032 GiB |

Currently mounted `/mnt/sunshine` shape:

| Area | Files | Size |
|---|---:|---:|
| `archive-2026-05-25` | 8,116 | 37.829 GiB |
| `Sunshine shared folders` | 557 | 9.675 GiB |
| `Paige Agent Sunshine Files` | 548 | 0.585 GiB |
| `From Mac Sunshine Pass 2026-05-25` | 165 | 0.082 GiB |
| `google-drive-delta-2026-05-25` | 77 | 0.016 GiB |
| `_manifest` | 19 | 0.060 GiB |

Currently mounted content-class heuristic:

| Content class | Files | Size |
|---|---:|---:|
| `image_photo_or_document_like` | 7,720 | 37.828 GiB |
| `text_document` | 1,055 | 0.123 GiB |
| `scanned_document_image` | 236 | 2.409 GiB |
| `pdf_document_or_scan` | 141 | 5.575 GiB |
| `code_or_workspace_artifact` | 132 | 0.020 GiB |
| `manifest_or_workspace_artifact` | 77 | 0.070 GiB |
| `spreadsheet_or_tabular` | 71 | 0.136 GiB |
| `presentation` | 15 | 0.033 GiB |
| `email` | 4 | very small |

Observed source folder themes under `Sunshine shared folders/` include `Admin Docs`, `Anniversaries`, `Articles and Features`, `Central History`, `Correspondence`, `Dental Clinics`, `Dental Support`, `Historian`, `Historical Photos`, `Meeting and Event photos`, `Minutes-agendas- dental reports and treasurer reports`, `Scholarship`, `Scrapbooks`, `Stewart Family Foundation`, `Sunshine Website and social media`, `Teas`, `Treasurer`, and `Tributes and Obituaries`.

Observed archive/workspace themes under `archive-2026-05-25/` include minutes transcription, yearbook reset/OCR intake, scrapbook inventories, budget review, history book resources, dental clinic collateral, document intake from Slack uploads, governance/policy work, online payments, insurance, interactive map code, and Paige work/tmp/vault artifacts.

## Proposed Primary Tags

These are the Verdify primary routing tags. They control routing intent only. More specific cross-cutting meaning belongs in secondary facets.

| Primary tag | Folder | Rule | Confidence | Evidence |
|---|---|---|---|---|
| `runbooks_handoff` | `00_READ_ME_AND_RUNBOOKS` | `flat` | High | Verdify handoff, runbooks, taxonomy docs, project briefs. |
| `governance_bylaws_policy` | `01_Governance_Admin` | `flat` | High | `Admin Docs`, articles of incorporation, governing documents, bylaws/policy update, governance survey material. |
| `meeting_records` | `01_Governance_Admin` | `by_year` | High | `Minutes-agendas- dental reports and treasurer reports`, annual school-year folders, agenda-only evidence, minutes transcriptions. |
| `finance_treasurer_records` | `02_Finance_Donations` | `by_year` | High | `Treasurer`, budget review, treasurer reports, financial analysis workbooks. |
| `donations_receipts_fundraising` | `02_Finance_Donations` | `by_year` | High | PayPal/payment trackers, Tea receipts, bake sale and donation records. |
| `membership_rosters_yearbooks` | `03_Membership` | `by_year` | High | yearbooks, member/officer archives, senior active lists, Family Ties, officer verification workbooks. |
| `dental_program` | `04_Programs_Partnerships` | `by_year` | High | `Dental Clinics`, dental support, dental clinic photos/collateral, dental report mentions. |
| `senior_smiles` | `04_Programs_Partnerships` | `by_year` | Medium-high | Existing Senior Smiles folder and senior dental references; lower volume than general dental. |
| `scholarships` | `04_Programs_Partnerships` | `by_year` | High | `Scholarship`, dental career scholarship application, beneficiary-sensitive examples. |
| `partner_programs` | `04_Programs_Partnerships` | `by_year` | High | Atwood, Stewart Family Foundation, Rotary, SVVSD, Longmont Museum, First Congregational references. |
| `annual_spring_tea` | `05_Events` | `by_year` | High | `Teas` has annual folders from 1902 through 2025; Tea workbooks, invitations, receipts, guest/bake-sale material. |
| `other_events` | `05_Events` | `by_year` | High | meeting/event photos, Christmas, Valentine, St. Patrick's, luncheons, picnics, museum event logistics. |
| `history_archive_general` | `06_History_Archive` | `by_year` | High | Central History, Historian, history book resources, transcriptions, general archive material. |
| `scrapbooks` | `06_History_Archive` | `by_year` | High | Scrapbook folders, Green/Brown/Small Green/1990s/2005-2009/2010-2014 inventories and scans. |
| `historical_photos` | `06_History_Archive` | `by_year` | High | Manifest image dominance, Historical Photos, extracted scrapbook photos, event and website photos. |
| `press_publications` | `06_History_Archive` | `by_year` | High | Articles and Features, press clippings, obituaries/tributes, public history publications. |
| `communications_templates` | `07_Communications` | `flat` | Medium-high | Correspondence, invitations, thank-yous, condolence/get-well/milestone language. |
| `website_public_materials` | `07_Communications` | `flat` | High | Website/social media folders, public web assets and copy. |
| `operations_assets` | `08_Operations_Assets` | `flat` | Medium-high | name tags/labels, magnets, supplies, silver inventory style material, operational checklists. |
| `legal_insurance_compliance` | `08_Operations_Assets` | `by_year` | High | Insurance, legal/IRS-sensitive compliance material, insurance applications. |
| `anniversary_125th` | `09_125th_Anniversary` | `flat` | High | 125th deck, survey summary, committee/project planning, current 2026 planning. |
| `cookbook_project` | `09_125th_Anniversary` | `flat` | Medium | Cookbook appears in project/workbook taxonomy and anniversary planning; corpus evidence is lower than Tea/scrapbooks. |
| `documentary_project` | `09_125th_Anniversary` | `flat` | Medium | Documentary appears in Verdify handoff and anniversary planning; route active project files here. |
| `central_garden_project` | `09_125th_Anniversary` | `flat` | Medium | Central Garden appears in Verdify handoff and anniversary planning; route active project files here. |
| `system_exports_logs` | `99_System_Exports_Logs` | `by_year_month` | High | `_manifest`, comparison TSV/JSON, rsync logs, Paige workspace artifacts, source-path snapshots, code/tmp files. |

Required secondary facets in V1: `record_type`, `function`, `program_project_event`, `source_collection`, `privacy_access`, `processing_status`, `usage`, and `reviewer_role`.

## Proposed Top-Level Folder Structure

High-confidence recommendation:

```text
00_READ_ME_AND_RUNBOOKS/
01_Governance_Admin/
02_Finance_Donations/
03_Membership/
04_Programs_Partnerships/
05_Events/
06_History_Archive/
07_Communications/
08_Operations_Assets/
09_125th_Anniversary/
90_Intake_Needs_Review/
99_System_Exports_Logs/
```

This matches the Verdify handoff's canonical folder families. Publications and public history route through the relevant primary tags, especially `press_publications` and `website_public_materials`; photos route through `historical_photos` when they are true photo/media records.

Tentative alternative: create a separate top-level `06_Photos_Media` if Google Drive users strongly expect to browse photos apart from source archive context. I do not recommend that as the default because many observed photos are scrapbook pages, clippings, rendered pages, or document-like scans. Splitting “photos” too early would erase useful provenance unless the DB preserves the source collection carefully.

## Proposed Placement Rules

Use these rule types in V1:

- `flat`
- `by_year`
- `by_year_month`

Files that are uncertain, duplicate-held, privacy-blocked, or unmapped should be held in `90_Intake_Needs_Review` by workflow state. The Verdify seed does not make review intake a normal semantic primary tag.

Recommended rules:

| Primary tag | Rule | Date source |
|---|---|---|
| `runbooks_handoff` | `flat` | upload date |
| `governance_bylaws_policy` | `flat` | document date |
| `meeting_records` | `by_year` | document or meeting date |
| `finance_treasurer_records` | `by_year` | document/report date |
| `donations_receipts_fundraising` | `by_year` | transaction/report/document date |
| `membership_rosters_yearbooks` | `by_year` | roster/yearbook/status year |
| `dental_program` | `by_year` | program/document date |
| `senior_smiles` | `by_year` | program/document date |
| `scholarships` | `by_year` | award/application/document date |
| `partner_programs` | `by_year` | program/document date |
| `annual_spring_tea` | `by_year` | event/document date |
| `other_events` | `by_year` | event/document date |
| `history_archive_general` | `by_year` | item/document date |
| `scrapbooks` | `by_year` | page/item/document date, with source collection and page order preserved in metadata |
| `historical_photos` | `by_year` | captured date, folder/event year, filename year, import year as last resort |
| `press_publications` | `by_year` | publication/date-of-item |
| `communications_templates` | `flat` | upload date |
| `website_public_materials` | `flat` | publication/upload date |
| `operations_assets` | `flat` for living assets; `by_year` for insurance/forms/inventories | document/effective date |
| `legal_insurance_compliance` | `by_year` | document/effective date |
| `anniversary_125th` | `flat` | project, committee, or milestone |
| `cookbook_project` | `flat` | project milestone |
| `documentary_project` | `flat` | project milestone |
| `central_garden_project` | `flat` | project milestone |
| `system_exports_logs` | `by_year_month` | manifest/import run date |

Specific objective-year guidance:

- Annual Tea and event material should use `by_year`; the corpus has explicit Tea folders from `1902 Fundraiser` through `2025 Tea`.
- Meeting records should use school/club-year ranges where already explicit, such as `2024-2025`, rather than forcing a single calendar year.
- Photos should use captured year only when EXIF or folder context is credible; many observed image filenames are generic `IMG_####` and need source-path/event inference.
- Scrapbooks should not be flattened purely by year. Preserve volume/page order first, then store item dates and years in DB metadata.
- Finance and donation files should use financial/document year, not necessarily import year.
- System manifests should use import batch timestamp, such as `2026-05-25T1205MDT-sunshine-inventory`, via `system_exports_logs` and `by_year_month`.

## File-Class Handling Recommendations

### Photos

High confidence: bypass normal text-centric semantic routing for low-text photos. Use content class, EXIF/captured date, path context, folder-derived event/year, filename clues, and review state.

Observed evidence:

- Manifested `jpg` + `jpeg` count is 28,900 files and about 134.4 GiB.
- Mounted `/mnt/sunshine` has 7,720 image-like files totaling about 37.8 GiB.
- Photo-like paths include `Historical Photos`, `Meeting and Event photos`, dental clinic collateral, `Individual Photos for Google Photos`, and generic resized `IMG_####.jpg/jpeg` pairs.

V1 behavior:

- Classify as `photo` or `document_like_image` before semantic tagging.
- Route true photos by year/event/review status.
- Use secondary facets for people/entities, event/program, source collection, privacy/access, processing status, usage, and publication readiness.

### Scanned Documents

High confidence: TIFFs, rendered pages, scrapbook pages, and scanned PDFs need OCR and provenance preservation.

Observed evidence:

- Manifested `tif`: 1,039 files / about 11.8 GiB.
- Mounted TIFF examples include tribute/obituary pages such as `Tributes and Obituaries/1911_Ruth Steven/page 28 copy.tif`.
- Google Drive delta contains rendered PNG pages from `2026_Sunshine_Club_Book_Proof.pdf`.

V1 behavior:

- Detect document-like images separately from photos.
- OCR before semantic classification where possible.
- Preserve page number, volume, source path, and OCR confidence.

### Receipts and Finance

High confidence: route receipts, payment exports, and finance workbooks through `finance_treasurer_records` or `donations_receipts_fundraising`, not event folders, when donor/payment details are the controlling risk.

Observed evidence:

- Paths include `Treasurer`, `Tea Receipts`, `Payment Links and Info`, `Budget Review 2016-2026`, PayPal/bake sale trackers, and source-text treasurer reports.

V1 behavior:

- Extract spreadsheet tables, dates, amounts, payer/donor-sensitive fields, and report periods.
- Default privacy to treasurer-only or donor-sensitive until reviewed.
- Secondary event tag can link a Tea payment workbook to Annual Spring Tea without controlling routing.

### Emails

Medium confidence from mounted files, high confidence from manifested count.

Observed evidence:

- Manifested `eml`: 225 files.
- Mounted examples include `.msg` invitation-list files under the archive.

V1 behavior:

- Preserve headers, sender, recipients, sent date, subject, body, attachments, and original folder.
- Treat emails with private member/donor data as restricted.
- Do not route based only on attachment filename; classify email body and attachments separately where needed.

### Spreadsheets

High confidence: spreadsheets are first-class structured sources, not just documents.

Observed evidence:

- Manifested `xlsx`: 175, plus CSV/TSV.
- Mounted examples include `Members_Master.xlsx`, `Membership Changes.xlsx`, `Compare Family Ties.xlsx`, scrapbook inventories, officer verification TSV/CSV, budget/payment trackers, and image inventories.

V1 behavior:

- Preserve workbook, sheet names, rows, date-like columns, formulas if available, and table context.
- Classify spreadsheet purpose after extraction: membership, finance, event tracker, inventory, or system manifest.
- Inventory spreadsheets generated during processing should route to `system_exports_logs`, not semantic folders.

### Event Material

High confidence: events deserve one primary tag and one top-level folder, with Tea as a key secondary tag.

Observed evidence:

- `Teas` has many year-named folders.
- Event material also appears as bake sale workbooks, invitations, meeting/event photos, Christmas/Valentine/St. Patrick's folders, annual meeting and luncheon material.

V1 behavior:

- Primary route to `events`.
- Use event name and year as deterministic placement components when obvious.
- Route finance/donor exports from events to `donations_receipts_fundraising` or `finance_treasurer_records` with secondary `annual_spring_tea`.

### Reports

Medium-high confidence: reports are semantically diverse and should not all route to one folder.

Observed evidence:

- Treasurer reports, dental reports, historian reports, annual meeting records, budget packets, and AI-generated research summaries appear across the corpus.

V1 behavior:

- Classify report by controlling function: finance, governance/meeting, programs, history, or system/research artifact.
- Store document type `report` as a secondary/document-type field.

### Manifests and Workspace Artifacts

High confidence: keep them, but exclude from normal user search/chat by default.

Observed evidence:

- `_manifest` includes JSON/TSV/CSV inventories, compare outputs, rsync logs, download summaries.
- Paige archive includes code, tmp, `.git`, Slack sync JSON/TXT, OCR tests, prior repo copies, and processing outputs.
- Actual mounted duplicate filename+size groups are high: 2,446 groups / 2,877 extra copies, inflated by copied workspaces and repeated scrapbook trees.

V1 behavior:

- Assign content class `manifest` or `code_or_workspace_artifact`.
- Route to `99_System_Exports_Logs` or ignore/admin-only views.
- Preserve as audit/provenance evidence.
- Exclude from normal user-facing search/chat unless explicitly promoted.

## Exclusions / Ignore Classes

High-confidence ignore or admin-only classes:

- Synology sidecars: `@eaDir`, `@SynoEAStream`, `@SynoResource`.
- OS trash and metadata: `#recycle`, `desktop.ini`, `.DS_Store`.
- Repo internals and generated code artifacts: `.git`, package caches, temporary local repo copies, build artifacts.
- Raw rsync and comparison logs, except under `99_System_Exports_Logs`.
- Manifest copies and pipeline-generated inventories unless reviewing provenance.
- Zero-byte or obviously failed exports should enter `90_Intake_Needs_Review` workflow state or failed extraction state, not normal routing. Observed example: `Linda Snyder.pdf` appears as 0 bytes in From Mac not-found candidates.
- Clearly unrelated `sunshine` homonyms outside the Sunshine Club corpus should remain excluded. Manifest notes already mention filtering unrelated music/retail uses of the word sunshine.

Do not exclude:

- Poor OCR scans.
- Low-text historical photos.
- Duplicates.
- Ambiguous scrapbook pages.

Those are real corpus material; they need review or content-class-specific handling, not deletion.

## Duplicate / Ambiguity Risks

High-confidence duplicate patterns:

- Repeated scrapbook folder variants: `Scrapbook`, `Scrapbook `, `Scrapbook (1)`, `Scrapbook (1) (1)`.
- Exact duplicates across `Source PDFs`, `Years Completed to upload`, `Local copy of transcriptions`, and `History book resources`.
- Same filename+size duplicates in From Mac: 619 groups and 2,039 extra copies.
- Document-focused comparison output reports 700 NAS document records, 689 focused Drive document records, 620 same-path/same-size matches, 79 NAS docs missing at same Drive path, 67 Drive docs missing at same NAS path, and 72 Drive duplicate-name groups.
- Google Drive full compare reports 19,212 Drive files, 19,135 same-path/same-size local matches, 74 missing local same-path files, and 3 size mismatches.
- Rendered derivatives: a PDF plus rendered `page-##.png`, OCR `.txt`, OCR `.docx`, and source scans may all represent the same logical item.
- Resized image pairs: observed `IMG_1899.jpeg` and `IMG_1899.jpg` style pairs in From Mac candidates.

High-confidence ambiguity patterns:

- Photos vs scanned pages vs scrapbook pages: extension alone is not enough.
- Events vs finance: Tea payment/donation workbooks are event-related, but payment data should route to finance.
- Governance vs operations: insurance and legal documents may be operational assets, governance/admin, or restricted legal material.
- Membership vs history: old yearbooks are both member records and historical artifacts.
- Obituaries/tributes: they are person/history records and may also be scrapbook clippings or membership context.
- Reports: treasurer, dental, historian, annual, and AI research reports need controlling function, not a generic reports folder.
- Current planning vs archive: 125th Anniversary files are active project material now, but older anniversary material may belong in history.

V1 duplicate handling should block routing when exact or near-duplicate evidence is present. Do not auto-delete. Preserve source collection, original path, checksum, size, mtime, and derived relationship evidence.

## Open Questions

1. Should true low-text photos have their own top-level Drive folder, or should they live under `06_History_Archive/Photos`? My recommendation is to start under `06_History_Archive/Photos` unless Drive users strongly prefer a standalone photo top-level.
2. Should meeting records live under `01_Governance_Admin` or a separate `Meeting Records` folder? My recommendation is `01_Governance_Admin` with secondary tags for minutes, agendas, dental reports, treasurer reports, and meeting year.
3. Are donor/payment exports expected to be in Google Drive at all, or should some remain in a separate restricted finance system with only summary artifacts in Drive?
4. Who is the authoritative reviewer for membership privacy, beneficiary-sensitive dental material, and publication-ready photos?
5. Should historical anniversary material route to `09_125th_Anniversary` or `06_History_Archive`? My recommendation: only active 125th project material routes to `09_125th_Anniversary`; historical anniversary source material routes to `history_archive`.
6. Which source collection is canonical when the same logical item exists in Drive, From Mac, NAS archive, and Paige workspace outputs?
7. Should OCR derivatives be stored beside originals in Drive, or should Sunshine Club DB hold extracted text while Drive keeps only source/original files?

## Specific Recommendations for Sunshine Club V1

High-confidence V1 scope:

1. Create the 12 top-level folders listed above manually in Google Drive.
2. Create the 12 V1 primary routing tags listed above in Sunshine Club DB.
3. Map every primary tag to exactly one top-level folder.
4. Require every primary tag to have an explicit placement rule before auto-routing.
5. Add content class before extraction: document, scanned document, photo/image, spreadsheet, presentation, email, manifest, workspace artifact, binary/unknown.
6. Implement deterministic `by_year`, `by_year_month`, and `flat` placement rules first, with review intake handled by workflow state.
7. Treat low-text photos as photo workflow items, not normal semantic document classification items.
8. Treat receipts, donation exports, PayPal trackers, and treasurer workbooks as restricted finance unless reviewed otherwise.
9. Put manifests, comparison outputs, logs, Paige tmp/workspace files, and source-path snapshots into admin-only system handling.
10. Make duplicate detection a blocker before routing for the historical corpus.
11. Build a 50-100 file golden labeling set before broad classification. Include Tea folders, a finance workbook, a yearbook/OCR item, a scrapbook page, a true photo, a scanned obituary, an email, a governance/policy doc, a dental program item, and a manifest/workspace artifact.

Wait until after V1 review data:

- Separate top-level folders for individual programs such as Dental Program, Senior Smiles, Scholarships, Rotary, or Tea.
- `by_year_month` folder placement.
- Fine-grained automated person/family routing.
- Automatic public/private publication decisions.
- Full version lineage graphs beyond duplicate/near-duplicate review.
- Moving OCR derivatives into Drive as separate canonical files.

Bottom line: V1 should optimize for controlled routing, provenance, duplicate safety, and review ergonomics. The DB should carry semantic richness; Drive folders should stay broad, stable, and manually governed.
