"use client";

import type { OcrEvidence } from "../../lib/types";
import { KeyValue } from "../ui/KeyValue";

export function OcrEvidencePanel({
  evidence,
  fallbackText,
  finalText,
}: {
  evidence?: OcrEvidence | null;
  fallbackText?: string | null;
  finalText?: string | null;
}) {
  const finalSnippet = evidence?.final_text_snippet || finalText || fallbackText || null;
  return (
    <div className="ocrEvidencePanel">
      <KeyValue label="Fallback used" value={evidence?.fallback_used ? "yes" : "no"} />
      <KeyValue label="Fallback provider" value={evidence?.fallback_provider ?? "-"} />
      <KeyValue label="Fallback reason" value={evidence?.fallback_reason ?? "-"} />
      {(evidence?.fallback_notes ?? []).length ? <KeyValue label="Fallback notes" value={(evidence?.fallback_notes ?? []).join("; ")} /> : null}
      <SnippetBlock label="Original OCR snippet" text={evidence?.original_text_snippet} empty="No original OCR snippet captured." />
      <SnippetBlock label="Fallback OCR snippet" text={evidence?.fallback_text_snippet || fallbackText} empty="No fallback OCR snippet captured." />
      <SnippetBlock label="Final selected text" text={finalSnippet} empty="No final text available." />
    </div>
  );
}

function SnippetBlock({ label, text, empty }: { label: string; text?: string | null; empty: string }) {
  return (
    <div className="snippetBlock">
      <span>{label}</span>
      <div className="textPreview compactTextPreview">{text || empty}</div>
    </div>
  );
}
