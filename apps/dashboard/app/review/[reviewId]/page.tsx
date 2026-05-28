"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";

import { OcrEvidencePanel } from "../../../components/dashboard/OcrEvidencePanel";
import { ProviderConfigBadge } from "../../../components/dashboard/ProviderConfigBadge";
import { RunContextBadge } from "../../../components/dashboard/RunContextBadge";
import { EmbeddedPreview } from "../../../components/file-preview/EmbeddedPreview";
import { Button } from "../../../components/ui/Button";
import { CheckboxField, SelectInput, TextArea, TextInput } from "../../../components/ui/FormControls";
import { KeyValue } from "../../../components/ui/KeyValue";
import { MultiTagPicker, TagPicker } from "../../../components/ui/TagPicker";
import { fetchJson, postJson, queryString } from "../../../lib/api";
import { contentClassOptions, ocrQualityOptions, primaryTagOptions, privacyOptions, secondaryTagOptions } from "../../../lib/taxonomy";
import type { ReviewItem } from "../../../lib/types";

export default function ReviewItemPage() {
  return (
    <Suspense fallback={<ReviewItemLoading />}>
      <ReviewItemPageContent />
    </Suspense>
  );
}

function ReviewItemLoading() {
  return (
    <main className="pageShell">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Review Item</p>
          <h1>Loading Review Item</h1>
        </div>
      </header>
      <div className="empty">Loading review item...</div>
    </main>
  );
}

function ReviewItemPageContent() {
  const params = useParams<{ reviewId: string }>();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const reviewId = params.reviewId;
  const source = searchParams.get("source") === "postgres" ? "postgres" : "sqlite";
  const sourceQuery = queryString({ source });
  const backHref = useMemo(() => {
    const filters = new URLSearchParams(searchParams);
    return `/review${filters.toString() ? `?${filters.toString()}` : ""}`;
  }, [searchParams]);

  const itemQuery = useQuery({
    queryKey: ["review-item", source, reviewId],
    queryFn: () => fetchJson<ReviewItem>(`/api/admin/review/items/${reviewId}${sourceQuery}`)
  });
  const textQuery = useQuery({
    queryKey: ["review-item-text", source, reviewId],
    queryFn: async () => {
      const response = await fetch(`/api/admin/review/items/${reviewId}/text${sourceQuery}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`${response.status} ${response.statusText}`);
      }
      return response.text();
    }
  });
  const decisionMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => postJson<ReviewItem>(`/api/admin/review/items/${reviewId}/decision${sourceQuery}`, body),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["review-item", source, reviewId] }),
        queryClient.invalidateQueries({ queryKey: ["review-items"] }),
        queryClient.invalidateQueries({ queryKey: ["review-summary"] })
      ]);
    }
  });
  const assignmentMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => postJson<ReviewItem>(`/api/admin/review/items/${reviewId}/assign`, body),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["review-item", source, reviewId] }),
        queryClient.invalidateQueries({ queryKey: ["review-items"] })
      ]);
    }
  });
  const ocrQualityMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => postJson<ReviewItem>(`/api/admin/review/items/${reviewId}/ocr-quality`, body),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["review-item", source, reviewId] }),
        queryClient.invalidateQueries({ queryKey: ["review-items"] }),
        queryClient.invalidateQueries({ queryKey: ["review-facets"] })
      ]);
    }
  });

  if (itemQuery.isLoading) {
    return <ReviewItemLoading />;
  }
  if (itemQuery.isError || !itemQuery.data) {
    return (
      <main className="pageShell">
        <header className="pageHeader">
          <div>
            <p className="eyebrow">Review Item</p>
            <h1>Review Item Not Found</h1>
          </div>
          <Link className="secondaryButton" href={backHref}>Back to Review</Link>
        </header>
        <div className="empty">Review item failed to load.</div>
      </main>
    );
  }

  const item = itemQuery.data;
  const extractedText = textQuery.data || item.extraction_text_snippet || "No text snippet available.";

  return (
    <main className="fileViewerPage">
      <header className="fileViewerHeader">
        <div>
          <p className="eyebrow">Review Item</p>
          <h1>{item.relative_path}</h1>
          <p className="muted">{item.source_path}</p>
        </div>
        <div className="buttonRow">
          <Link className="secondaryButton" href={backHref}>Back to Review</Link>
          <a className="secondaryButton" href={`/api/admin/review/items/${item.id}/download${sourceQuery}`} download>Download File</a>
          {typeof item.run_id === "number" ? <Link className="secondaryButton" href={`/runs/${item.run_id}/report`}>Run Report</Link> : null}
        </div>
      </header>

      <section className="fileViewerText">
        <div>
          <h2>Extracted Text</h2>
          <div className="textMetaRow">
            <span>Status {item.status}</span>
            <span>Reason {item.review_reason ?? "-"}</span>
            <span>Confidence {item.confidence == null ? "-" : item.confidence.toFixed(2)}</span>
          </div>
        </div>
        <div className="textPreview fileViewerReadableText">{extractedText}</div>
      </section>

      <section className="fileViewerPreview">
        <EmbeddedPreview previewUrl={`/api/admin/review/items/${item.id}/file${sourceQuery}`} filename={item.relative_path || item.source_path} autoLoad />
      </section>

      <section className="fileViewerDetailsGrid">
        <section className="drawerSection">
          <h2>Run Context</h2>
          <KeyValue label="Run" value={<RunContextBadge runId={item.run_id} runKey={item.run_key} preset={item.run_preset_key} />} />
          <KeyValue label="Providers" value={<ProviderConfigBadge embeddingProvider={item.embedding_provider} llmEnabled={item.enable_llm_tags} llmProvider={item.llm_tag_provider} ocrProvider={item.ocr_fallback_provider} />} />
          <KeyValue label="Class" value={item.proposed_class ?? "-"} />
          <KeyValue label="Primary tag" value={item.proposed_tag ?? "-"} />
          <KeyValue label="Secondary tags" value={item.secondary_tags.join(", ") || "-"} />
          <KeyValue label="Warnings" value={(item.display_warnings ?? item.warnings).join(", ") || "-"} />
        </section>

        <section className="drawerSection">
          <h2>OCR Evidence</h2>
          <KeyValue label="Reviewer OCR label" value={item.ocr_quality_label ?? "-"} />
          <OcrEvidencePanel
            evidence={item.ocr_evidence ?? item.result.ocr_evidence}
            fallbackText={item.extraction_text_snippet}
            finalText={extractedText}
          />
        </section>

        <section className="drawerSection">
          <h2>Placement</h2>
          <KeyValue label="Destination" value={item.result.destination_path ?? "-"} />
          <KeyValue label="Status" value={item.result.placement_status ?? "-"} />
          <KeyValue label="Rule" value={item.result.placement_rule ?? "-"} />
          <KeyValue label="Date confidence" value={item.result.placement_date_confidence ?? "-"} />
          <KeyValue label="Privacy" value={item.result.default_privacy ?? "-"} />
        </section>

        <ReviewDecisionPanel
          item={item}
          saving={decisionMutation.isPending}
          assigning={assignmentMutation.isPending || ocrQualityMutation.isPending}
          supportsAssignment={source === "sqlite"}
          supportsOcrQuality={source === "sqlite"}
          onSubmit={(body) => decisionMutation.mutate(body)}
          onAssign={(body) => assignmentMutation.mutate(body)}
          onMarkOcrPoor={(body) => ocrQualityMutation.mutate(body)}
        />
      </section>

      <section className="fileViewerText">
        <h2>Evidence</h2>
        <div className="evidenceGrid">
          <section>
            <h3>Tag Evidence</h3>
            <ul className="evidenceList">{(item.result.tag_evidence ?? []).map((evidence) => <li key={evidence}>{evidence}</li>)}</ul>
            {(item.result.tag_evidence ?? []).length ? null : <p className="muted">No tag evidence available.</p>}
          </section>
          <section>
            <h3>Nearest Examples</h3>
            {(item.result.semantic_examples ?? []).length ? (
              <ul className="evidenceList">
                {(item.result.semantic_examples ?? []).map((example, index) => (
                  <li key={`${example.relative_path}-${index}`}>
                    {example.correct_primary_tag} {example.score?.toFixed(3)} {example.relative_path}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No semantic examples used.</p>
            )}
          </section>
        </div>
      </section>
    </main>
  );
}

function ReviewDecisionPanel({
  item,
  saving,
  assigning,
  supportsAssignment,
  supportsOcrQuality,
  onSubmit,
  onAssign,
  onMarkOcrPoor
}: {
  item: ReviewItem;
  saving: boolean;
  assigning: boolean;
  supportsAssignment: boolean;
  supportsOcrQuality: boolean;
  onSubmit: (body: Record<string, unknown>) => void;
  onAssign: (body: Record<string, unknown>) => void;
  onMarkOcrPoor: (body: Record<string, unknown>) => void;
}) {
  const [decision, setDecision] = useState("accept");
  const [correctClass, setCorrectClass] = useState(item.correct_class ?? item.proposed_class ?? "");
  const [correctTag, setCorrectTag] = useState(item.correct_tag ?? item.proposed_tag ?? "");
  const [secondary, setSecondary] = useState(item.correct_secondary_tags?.length ? item.correct_secondary_tags : item.secondary_tags);
  const [ocrQuality, setOcrQuality] = useState(item.ocr_quality_label ?? String(item.result.quality ?? ""));
  const [expectedReviewRequired, setExpectedReviewRequired] = useState(item.expected_review_required ?? item.route_status !== "route_candidate");
  const [sensitiveRecord, setSensitiveRecord] = useState(Boolean(item.sensitive_record));
  const [destination, setDestination] = useState(item.correct_destination_path ?? item.result.destination_path ?? "");
  const [placementYear, setPlacementYear] = useState(item.correct_placement_year ?? "");
  const [privacy, setPrivacy] = useState(item.correct_privacy ?? item.result.default_privacy ?? "");
  const [reviewStage, setReviewStage] = useState(item.review_stage ?? "");
  const [assignedReviewer, setAssignedReviewer] = useState(item.assigned_reviewer ?? "");
  const [priority, setPriority] = useState(item.priority ?? "");
  const [notes, setNotes] = useState(item.notes ?? "");
  const [reviewer, setReviewer] = useState("james");
  const [saveAsGolden, setSaveAsGolden] = useState(decision === "accept" || decision === "change");

  return (
    <section className="drawerSection">
      <h2>Decision</h2>
      <div className="formGrid">
        <SelectInput
          label="Decision"
          value={decision}
          onChange={(event) => {
            const nextDecision = event.target.value;
            setDecision(nextDecision);
            setSaveAsGolden(nextDecision === "accept" || nextDecision === "change");
          }}
        >
          <option value="accept">Accept</option>
          <option value="change">Change</option>
          <option value="defer">Defer</option>
          <option value="ignore">Ignore</option>
          <option value="reject">Reject</option>
          <option value="duplicate">Duplicate</option>
        </SelectInput>
        <SelectInput label="Correct class" value={correctClass} onChange={(event) => setCorrectClass(event.target.value)}>
          <option value="">Unset</option>
          {contentClassOptions.map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </SelectInput>
        <TagPicker label="Correct primary tag" options={primaryTagOptions} value={correctTag} onChange={setCorrectTag} />
        <MultiTagPicker label="Correct secondary tags" options={secondaryTagOptions} value={secondary} onChange={setSecondary} />
        <SelectInput label="OCR quality label" value={ocrQuality} onChange={(event) => setOcrQuality(event.target.value)}>
          <option value="">Unset</option>
          {ocrQualityOptions.map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </SelectInput>
        <TextInput label="Correct destination path" value={destination} onChange={(event) => setDestination(event.target.value)} />
        <TextInput label="Correct placement year/range" value={placementYear} onChange={(event) => setPlacementYear(event.target.value)} />
        <SelectInput label="Correct privacy" value={privacy} onChange={(event) => setPrivacy(event.target.value)}>
          <option value="">Unset</option>
          {privacyOptions.map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </SelectInput>
        <CheckboxField label="Expected review required" checked={expectedReviewRequired} onChange={(event) => setExpectedReviewRequired(event.target.checked)} />
        <CheckboxField label="Sensitive record" checked={sensitiveRecord} onChange={(event) => setSensitiveRecord(event.target.checked)} />
        <CheckboxField label="Promote decision to golden label" checked={saveAsGolden} onChange={(event) => setSaveAsGolden(event.target.checked)} />
        <TextInput label="Review stage" value={reviewStage} onChange={(event) => setReviewStage(event.target.value)} />
        <TextInput label="Assigned reviewer" value={assignedReviewer} onChange={(event) => setAssignedReviewer(event.target.value)} />
        <TextInput label="Priority" value={priority} onChange={(event) => setPriority(event.target.value)} />
        <TextInput label="Reviewer" value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
        <TextArea label="Notes" value={notes} onChange={(event) => setNotes(event.target.value)} rows={4} />
        <Button
          disabled={assigning || !supportsOcrQuality}
          onClick={() => {
            setOcrQuality("poor");
            setExpectedReviewRequired(true);
            setReviewStage("needs_ocr_review");
            onMarkOcrPoor({
              ocr_quality_label: "poor",
              review_stage: "needs_ocr_review",
              notes: "Marked OCR poor from review dashboard."
            });
          }}
        >
          Mark OCR Poor
        </Button>
        <Button
          disabled={assigning || !supportsAssignment}
          onClick={() =>
            onAssign({
              assigned_reviewer: assignedReviewer || null,
              review_stage: reviewStage || null,
              priority: priority || null
            })
          }
        >
          {assigning ? "Assigning..." : "Save Assignment"}
        </Button>
        <Button
          variant="primary"
          disabled={saving}
          onClick={() =>
            onSubmit({
              decision,
              correct_class: correctClass || null,
              correct_tag: correctTag || null,
              correct_secondary_tags: secondary,
              ocr_quality_label: ocrQuality || null,
              expected_review_required: expectedReviewRequired,
              sensitive_record: sensitiveRecord,
              correct_destination_path: destination || null,
              correct_placement_year: placementYear || null,
              correct_privacy: privacy || null,
              review_stage: reviewStage || null,
              notes,
              reviewer: reviewer || null,
              save_as_golden: saveAsGolden
            })
          }
        >
          {saving ? "Saving..." : "Save Decision"}
        </Button>
      </div>
    </section>
  );
}
