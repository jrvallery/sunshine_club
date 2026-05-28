"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "../../components/ui/Button";
import { CheckboxField, SelectInput, TextArea, TextInput } from "../../components/ui/FormControls";
import { KeyValue } from "../../components/ui/KeyValue";
import { MultiTagPicker, TagPicker } from "../../components/ui/TagPicker";
import { deleteJson, fetchJson, patchJson, postJson } from "../../lib/api";
import { contentClassOptions, ocrQualityOptions, primaryTagOptions, privacyOptions, secondaryTagOptions } from "../../lib/taxonomy";
import type { GoldenLabel, GoldenLabelSummary, SemanticIndexStatus } from "../../lib/types";

export default function GoldenLabelsPage() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<GoldenLabel | null>(null);
  const [onlyMismatches, setOnlyMismatches] = useState(false);
  const [primaryFilter, setPrimaryFilter] = useState("");
  const [secondaryFilter, setSecondaryFilter] = useState("");
  const labels = useQuery({
    queryKey: ["golden-labels"],
    queryFn: () => fetchJson<GoldenLabel[]>("/api/admin/review/golden-labels?limit=500")
  });
  const summary = useQuery({
    queryKey: ["golden-label-summary"],
    queryFn: () => fetchJson<GoldenLabelSummary>("/api/admin/review/golden-labels/summary")
  });
  const indexStatus = useQuery({
    queryKey: ["semantic-index-status"],
    queryFn: () => fetchJson<SemanticIndexStatus>("/api/admin/semantic-index/status")
  });
  const buildIndex = useMutation({
    mutationFn: () => postJson<{ ok: boolean; status: SemanticIndexStatus }>("/api/admin/semantic-index/build", {}),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["semantic-index-status"] });
    }
  });
  const updateLabel = useMutation({
    mutationFn: (payload: { id: number; body: Record<string, unknown> }) =>
      patchJson<GoldenLabel>(`/api/admin/review/golden-labels/${payload.id}`, payload.body),
    onSuccess: async (label) => {
      setSelected(label);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["golden-labels"] }),
        queryClient.invalidateQueries({ queryKey: ["golden-label-summary"] })
      ]);
    }
  });
  const deleteLabel = useMutation({
    mutationFn: (id: number) => deleteJson<{ deleted: boolean }>(`/api/admin/review/golden-labels/${id}`),
    onSuccess: async () => {
      setSelected(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["golden-labels"] }),
        queryClient.invalidateQueries({ queryKey: ["golden-label-summary"] }),
        queryClient.invalidateQueries({ queryKey: ["semantic-index-status"] })
      ]);
    }
  });
  const visibleLabels = (labels.data ?? [])
    .filter((label) => !onlyMismatches || label.correct_primary_tag !== label.proposed_tag)
    .filter((label) => !primaryFilter || label.correct_primary_tag === primaryFilter)
    .filter((label) => !secondaryFilter || label.correct_secondary_tags.includes(secondaryFilter));
  const mismatchCount = (labels.data ?? []).filter((label) => label.correct_primary_tag !== label.proposed_tag).length;

  return (
    <main className="pageShell">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Training</p>
          <h1>Golden Labels</h1>
        </div>
        <div className="metricStrip">
          <Metric label="Total labels" value={summary.data?.total_golden_labels ?? 0} />
          <Metric label="Primary coverage" value={formatPercent(summary.data?.primary_coverage_rate)} />
          <Metric label="Indexed" value={indexStatus.data?.indexed ?? 0} />
          <Metric label="Mismatches" value={mismatchCount} />
        </div>
      </header>

      <section className="panel actionPanel">
        <div>
          <h2>Semantic Index</h2>
          <p className="muted">
            {indexStatus.data?.exists ? `${indexStatus.data.index_db} updated ${indexStatus.data.updated_at ?? "unknown"}` : "No semantic index found."}
          </p>
          <p className="muted">
            Provider: {indexStatus.data?.embedding_provider ?? "-"} / {indexStatus.data?.embedding_model ?? "-"} /{" "}
            {indexStatus.data?.embedding_dimensions ?? "-"} dims
          </p>
        </div>
        <Button variant="primary" disabled={buildIndex.isPending} onClick={() => buildIndex.mutate()}>
          {buildIndex.isPending ? "Building..." : "Build Semantic Index"}
        </Button>
      </section>

      <section className="panel actionPanel">
        <div>
          <h2>Golden Label Export</h2>
          <p className="muted">Download the reviewed golden set for audit, backup, or command-line evaluation runs.</p>
        </div>
        <div className="buttonRow">
          <a className="secondaryButton" href="/api/admin/review/golden-labels/export?format=csv&limit=10000" download>
            Export CSV
          </a>
          <a className="secondaryButton" href="/api/admin/review/golden-labels/export?format=jsonl&limit=10000" download>
            Export JSONL
          </a>
        </div>
      </section>

      <section className="bands">
        {Object.entries(summary.data?.golden_by_primary_tag ?? {}).map(([tag, count]) => (
          <div className="breakdown" key={tag}>
            <h2>{tag}</h2>
            <div className="metricValue">{count}</div>
          </div>
        ))}
      </section>

      <section className="panel">
        <div className="sectionHeader">
          <h2>Coverage Gaps</h2>
          <span>{summary.data?.missing_primary_tags?.length ?? 0} primary tags missing</span>
        </div>
        <div className="chipList">
          {(summary.data?.missing_primary_tags ?? []).map((tag) => (
            <button className="filterChip" key={tag} onClick={() => setPrimaryFilter(tag)}>
              {tag}
            </button>
          ))}
          {summary.data?.missing_primary_tags?.length === 0 ? <span className="muted">All primary taxonomy families have labels.</span> : null}
        </div>
      </section>

      <section className="panel">
        <div className="sectionHeader">
          <h2>Labels</h2>
          <CheckboxField label="Show proposed/correct mismatches" checked={onlyMismatches} onChange={(event) => setOnlyMismatches(event.target.checked)} />
        </div>
        <div className="filterBar compactFilterBar">
          <TagPicker label="Primary tag" options={primaryTagOptions} value={primaryFilter} onChange={setPrimaryFilter} />
          <TagPicker label="Secondary tag" options={secondaryTagOptions} value={secondaryFilter} onChange={setSecondaryFilter} />
        </div>
        <div className="tableWrap" tabIndex={0} aria-label="Golden labels table">
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Correct Primary</th>
                <th>Class</th>
                <th>OCR</th>
                <th>Correct Secondary</th>
                <th>Proposed</th>
                <th>Reviewer</th>
                <th>Reviewed</th>
              </tr>
            </thead>
            <tbody>
              {visibleLabels.map((label) => (
                <tr key={label.id}>
                  <td>
                    <button className="linkButton fileCell" onClick={() => setSelected(label)}>
                      <strong>{label.relative_path}</strong>
                      <span>{label.extracted_text_snippet ?? "No snippet"}</span>
                    </button>
                  </td>
                  <td>{label.correct_primary_tag}</td>
                  <td>{label.content_class ?? "-"}</td>
                  <td>{label.ocr_quality_label ?? "-"}</td>
                  <td>{label.correct_secondary_tags.join(", ") || "-"}</td>
                  <td>{label.proposed_tag ?? "-"}</td>
                  <td>{label.reviewer ?? "-"}</td>
                  <td>{label.reviewed_at ?? label.updated_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {selected ? (
        <GoldenLabelDrawer
          label={selected}
          saving={updateLabel.isPending}
          deleting={deleteLabel.isPending}
          onClose={() => setSelected(null)}
          onSave={(body) => updateLabel.mutate({ id: selected.id, body })}
          onDelete={() => deleteLabel.mutate(selected.id)}
        />
      ) : null}
    </main>
  );
}

function GoldenLabelDrawer({
  label,
  saving,
  deleting,
  onClose,
  onSave,
  onDelete
}: {
  label: GoldenLabel;
  saving: boolean;
  deleting: boolean;
  onClose: () => void;
  onSave: (body: Record<string, unknown>) => void;
  onDelete: () => void;
}) {
  const [primary, setPrimary] = useState(label.correct_primary_tag);
  const [secondary, setSecondary] = useState(label.correct_secondary_tags);
  const [contentClass, setContentClass] = useState(label.content_class ?? "");
  const [ocrQuality, setOcrQuality] = useState(label.ocr_quality_label ?? "");
  const [expectedReviewRequired, setExpectedReviewRequired] = useState(Boolean(label.expected_review_required));
  const [sensitiveRecord, setSensitiveRecord] = useState(Boolean(label.sensitive_record));
  const [destinationPath, setDestinationPath] = useState(label.correct_destination_path ?? "");
  const [placementYear, setPlacementYear] = useState(label.correct_placement_year ?? "");
  const [privacy, setPrivacy] = useState(label.correct_privacy ?? "");
  const [reviewer, setReviewer] = useState(label.reviewer ?? "");
  const [notes, setNotes] = useState(label.notes ?? "");

  return (
    <aside className="drawer">
      <div className="drawerHeader">
        <div>
          <p className="eyebrow">Golden Label</p>
          <h2>{label.relative_path}</h2>
        </div>
        <Button onClick={onClose}>
          Close
        </Button>
      </div>
      <div className="drawerGrid">
        <section className="wideSection">
          <h3>Evidence</h3>
          <p className="pathText">{label.source_path}</p>
          <div className="buttonRow">
            <a className="primaryButton" href={`/api/admin/review/golden-labels/${label.id}/file`} target="_blank">
              Open Source File
            </a>
          </div>
          <div className="textPreview">{label.extracted_text_snippet || "No extracted text snippet."}</div>
        </section>
        <section>
          <h3>Pipeline Proposal</h3>
          <KeyValue label="Primary" value={label.proposed_tag ?? "-"} />
          <KeyValue label="Secondary" value={label.proposed_secondary_tags?.join(", ") || "-"} />
          <KeyValue label="Confidence" value={label.proposed_confidence == null ? "-" : label.proposed_confidence.toFixed(2)} />
          <KeyValue label="Prediction status" value={label.correct_primary_tag === label.proposed_tag ? "matches" : "changed prediction"} />
        </section>
        <section>
          <h3>Quality Label</h3>
          <div className="formGrid">
            <SelectInput label="Content class" value={contentClass} onChange={(event) => setContentClass(event.target.value)}>
              <option value="">Unset</option>
              {contentClassOptions.map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </SelectInput>
            <SelectInput label="OCR quality" value={ocrQuality} onChange={(event) => setOcrQuality(event.target.value)}>
              <option value="">Unset</option>
              {ocrQualityOptions.map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </SelectInput>
            <CheckboxField label="Expected review required" checked={expectedReviewRequired} onChange={(event) => setExpectedReviewRequired(event.target.checked)} />
            <CheckboxField label="Sensitive record" checked={sensitiveRecord} onChange={(event) => setSensitiveRecord(event.target.checked)} />
          </div>
        </section>
        <section>
          <h3>Placement Label</h3>
          <div className="formGrid">
            <TextInput label="Correct destination path" value={destinationPath} onChange={(event) => setDestinationPath(event.target.value)} />
            <TextInput label="Correct year / year-month" value={placementYear} onChange={(event) => setPlacementYear(event.target.value)} />
            <SelectInput label="Correct privacy" value={privacy} onChange={(event) => setPrivacy(event.target.value)}>
              <option value="">Unset</option>
              {privacyOptions.map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </SelectInput>
          </div>
        </section>
        <section>
          <h3>Correct Label</h3>
          <div className="formGrid">
            <TagPicker label="Correct primary tag" options={primaryTagOptions} value={primary} onChange={setPrimary} />
            <MultiTagPicker label="Correct secondary tags" options={secondaryTagOptions} value={secondary} onChange={setSecondary} />
            <TextInput label="Reviewer" value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
            <TextArea label="Notes" value={notes} onChange={(event) => setNotes(event.target.value)} rows={5} />
            <Button
              variant="primary"
              disabled={saving}
              onClick={() =>
                onSave({
                  content_class: contentClass || null,
                  correct_primary_tag: primary,
                  correct_secondary_tags: secondary,
                  ocr_quality_label: ocrQuality || null,
                  expected_review_required: expectedReviewRequired,
                  sensitive_record: sensitiveRecord,
                  correct_destination_path: destinationPath || null,
                  correct_placement_year: placementYear || null,
                  correct_privacy: privacy || null,
                  reviewer,
                  notes
                })
              }
            >
              {saving ? "Saving..." : "Save Label"}
            </Button>
            <Button variant="danger" disabled={deleting} onClick={onDelete}>
              {deleting ? "Deleting..." : "Delete Label"}
            </Button>
          </div>
        </section>
      </div>
    </aside>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="miniMetric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "-";
  }
  return `${Math.round(value * 100)}%`;
}
