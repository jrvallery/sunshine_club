"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";

import { ProviderConfigBadge } from "../../../components/dashboard/ProviderConfigBadge";
import { RunContextBadge } from "../../../components/dashboard/RunContextBadge";
import { EmbeddedPreview } from "../../../components/file-preview/EmbeddedPreview";
import { KeyValue } from "../../../components/ui/KeyValue";
import { fetchJson, postJson } from "../../../lib/api";
import type { FileInspection, PipelineRun, ReviewItem } from "../../../lib/types";

export default function FileViewerPage() {
  return (
    <Suspense fallback={<main className="pageShell"><div className="empty">Loading file...</div></main>}>
      <FileViewerPageContent />
    </Suspense>
  );
}

function FileViewerPageContent() {
  const params = useParams<{ fileId: string }>();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const fileId = Number(params.fileId);
  const backHref = useMemo(() => {
    const filters = new URLSearchParams(searchParams);
    return `/files${filters.toString() ? `?${filters.toString()}` : ""}`;
  }, [searchParams]);
  const [embeddingProvider, setEmbeddingProvider] = useState("cortex");
  const [llmProvider, setLlmProvider] = useState("cortex");
  const [ocrProvider, setOcrProvider] = useState("cortex");

  const inspection = useQuery({
    queryKey: ["file-inspection", fileId],
    enabled: Number.isFinite(fileId),
    queryFn: () => fetchJson<FileInspection>(`/api/admin/files/${fileId}/inspection`)
  });
  const addReview = useMutation({
    mutationFn: () => postJson<ReviewItem>(`/api/admin/files/${fileId}/review`, { review_reason: "manual_file_review" }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["file-inspection", fileId] }),
        queryClient.invalidateQueries({ queryKey: ["review-items"] })
      ]);
    }
  });
  const runFile = useMutation({
    mutationFn: () =>
      postJson<PipelineRun>(`/api/admin/files/${fileId}/run`, {
        start: true,
        embedding_provider: embeddingProvider,
        enable_llm_tags: true,
        llm_tag_provider: llmProvider,
        ocr_fallback_provider: ocrProvider
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["runs"] }),
        queryClient.invalidateQueries({ queryKey: ["file-inspection", fileId] })
      ]);
    }
  });

  if (inspection.isLoading) {
    return <main className="pageShell"><div className="empty">Loading file...</div></main>;
  }
  if (inspection.isError || !inspection.data) {
    return (
      <main className="pageShell">
        <Link className="secondaryButton" href={backHref}>Back to Files</Link>
        <div className="empty">File inspection failed.</div>
      </main>
    );
  }

  const data = inspection.data;
  const file = data.file;
  const result = data.latest_result ?? {};

  return (
    <main className="fileViewerPage">
      <header className="fileViewerHeader">
        <div>
          <p className="eyebrow">File Viewer</p>
          <h1>{file.filename}</h1>
          <p className="muted">{file.relative_path}</p>
        </div>
        <div className="buttonRow">
          <Link className="secondaryButton" href={backHref}>Back to Files</Link>
          <a className="secondaryButton" href={`/api/admin/files/${file.id}/download`} download>Download File</a>
          {data.actions.latest_run_report_url ? <Link className="secondaryButton" href={data.actions.latest_run_report_url}>Run Report</Link> : null}
        </div>
      </header>

      <section className="fileViewerGrid">
        <section className="fileViewerPreview">
          <EmbeddedPreview
            previewUrl={`/api/admin/files/${file.id}/preview`}
            filename={file.filename}
            mimeType={file.mime_type ?? undefined}
            extension={file.extension ?? undefined}
            autoLoad
          />
        </section>

        <section className="fileViewerSidebar">
          <section className="drawerSection">
            <h2>Actions</h2>
            <div className="providerPickerGrid">
              <ProviderSelect label="Embedding path" value={embeddingProvider} onChange={setEmbeddingProvider} />
              <ProviderSelect label="LLM tag path" value={llmProvider} onChange={setLlmProvider} />
              <ProviderSelect label="OCR fallback path" value={ocrProvider} onChange={setOcrProvider} />
            </div>
            <div className="buttonRow">
              <button className="secondaryButton" onClick={() => copyText(file.source_path)}>Copy Path</button>
              <button className="secondaryButton" disabled={addReview.isPending} onClick={() => addReview.mutate()}>Add To Review</button>
              <button className="secondaryButton" disabled={runFile.isPending} onClick={() => runFile.mutate()}>Run File</button>
            </div>
          </section>

          <section className="drawerSection">
            <h2>Identity</h2>
            <KeyValue label="Relative path" value={file.relative_path} />
            <KeyValue label="Source path" value={file.source_path} />
            <KeyValue label="Collection" value={file.source_collection ?? "-"} />
            <KeyValue label="Type" value={`${file.extension ?? "-"} / ${file.content_class ?? "-"}`} />
            <KeyValue label="Size" value={file.size_bytes == null ? "-" : `${file.size_bytes} bytes`} />
            <KeyValue label="Latest run" value={<RunContextBadge runId={file.latest_run_id} runKey={file.latest_run_key} preset={file.latest_run_preset_key} />} />
            <KeyValue
              label="Latest providers"
              value={
                <ProviderConfigBadge
                  embeddingProvider={file.latest_embedding_provider}
                  llmEnabled={file.latest_enable_llm_tags}
                  llmProvider={file.latest_llm_tag_provider}
                  ocrProvider={file.latest_ocr_fallback_provider}
                />
              }
            />
          </section>

          <section className="drawerSection">
            <h2>Latest Pipeline Result</h2>
            <KeyValue label="Class" value={result.final_class ?? file.content_class ?? "-"} />
            <KeyValue label="Extraction" value={result.extraction_strategy ?? "-"} />
            <KeyValue label="Status" value={result.extraction_status ?? "-"} />
            <KeyValue label="Primary tag" value={result.top_tag_candidate ?? "-"} />
            <KeyValue label="Secondary tags" value={(result.secondary_tags ?? []).join(", ") || "-"} />
            <KeyValue label="Confidence" value={result.tag_confidence == null ? "-" : String(result.tag_confidence)} />
            <KeyValue label="Destination" value={result.destination_path ?? "-"} />
            <KeyValue label="Placement" value={result.placement_status ?? "-"} />
            <WarningList warnings={result.warnings ?? []} />
          </section>
        </section>
      </section>

      <section className="fileViewerText">
        <div>
          <h2>Extracted Text</h2>
          <div className="textMetaRow">
            <span>Length {data.text.length}</span>
            <span>OCR {String(data.ocr.quality ?? "-")}</span>
            <span>Confidence {String(data.ocr.mean_confidence ?? "-")}</span>
          </div>
        </div>
        <div className="textPreview fileViewerReadableText">{data.text.text || data.text.snippet || "No text available."}</div>
      </section>
    </main>
  );
}

function ProviderSelect({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label>
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="cortex">Cortex</option>
        <option value="openai">OpenAI</option>
      </select>
    </label>
  );
}

function copyText(value: string) {
  void navigator.clipboard?.writeText(value);
}

function WarningList({ warnings }: { warnings: string[] }) {
  if (!warnings.length) {
    return <KeyValue label="Warnings" value="-" />;
  }
  return (
    <div className="keyValue">
      <span>Warnings</span>
      <strong>{warnings.slice(0, 5).join("; ")}</strong>
    </div>
  );
}
