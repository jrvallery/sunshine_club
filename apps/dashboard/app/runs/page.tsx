"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Button } from "../../components/ui/Button";
import { CheckboxField, SelectInput, TextInput } from "../../components/ui/FormControls";
import { KeyValue } from "../../components/ui/KeyValue";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { deleteJson, fetchJson, postJson } from "../../lib/api";
import type { PipelineRun, PipelineRunComparison, PipelineRunEvent, PipelineRunProgress, PipelineRunResults, RunPreset } from "../../lib/types";

export default function RunsPage() {
  const queryClient = useQueryClient();
  const [selectedRun, setSelectedRun] = useState<PipelineRun | null>(null);
  const [selectedPreset, setSelectedPreset] = useState<RunPreset | null>(null);
  const presets = useQuery({ queryKey: ["run-presets"], queryFn: () => fetchJson<RunPreset[]>("/api/admin/runs/presets") });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => fetchJson<PipelineRun[]>("/api/admin/runs?limit=100"),
    refetchInterval: (query) => ((query.state.data ?? []).some((run) => run.status === "running" || run.status === "queued") ? 1500 : 5000)
  });
  const selectedRunDetail = useQuery({
    queryKey: ["run-detail", selectedRun?.id],
    enabled: Boolean(selectedRun),
    queryFn: () => fetchJson<PipelineRun>(`/api/admin/runs/${selectedRun?.id}`),
    refetchInterval: (query) => (query.state.data?.status === "running" || query.state.data?.status === "queued" ? 1500 : false)
  });
  const activeRun = selectedRunDetail.data ?? selectedRun;
  const progress = useQuery({
    queryKey: ["run-progress", selectedRun?.id],
    enabled: Boolean(selectedRun),
    queryFn: () => fetchJson<PipelineRunProgress>(`/api/admin/runs/${selectedRun?.id}/progress`),
    refetchInterval: activeRun?.status === "running" || activeRun?.status === "queued" ? 1500 : false
  });
  const events = useQuery({
    queryKey: ["run-events", selectedRun?.id],
    enabled: Boolean(selectedRun),
    queryFn: () => fetchJson<PipelineRunEvent[]>(`/api/admin/runs/${selectedRun?.id}/events`),
    refetchInterval: activeRun?.status === "running" || activeRun?.status === "queued" ? 1500 : false
  });
  const results = useQuery({
    queryKey: ["run-results", selectedRun?.id],
    enabled: Boolean(selectedRun),
    queryFn: () => fetchJson<PipelineRunResults>(`/api/admin/runs/${selectedRun?.id}/results`)
  });
  const comparison = useQuery({
    queryKey: ["run-comparison", selectedRun?.id],
    enabled: Boolean(selectedRun),
    queryFn: () => fetchJson<PipelineRunComparison>(`/api/admin/runs/${selectedRun?.id}/compare-previous`)
  });
  const startRun = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      postJson<PipelineRun>("/api/admin/runs", {
        start: true,
        import_on_success: false,
        ...payload
      }),
    onSuccess: async (run) => {
      setSelectedPreset(null);
      setSelectedRun(run);
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
    }
  });
  const importResults = useMutation({
    mutationFn: (runId: number) => postJson<Record<string, unknown>>(`/api/admin/runs/${runId}/import-results`, {}),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
    }
  });
  const cancelRun = useMutation({
    mutationFn: (runId: number) => postJson<PipelineRun>(`/api/admin/runs/${runId}/cancel`, {}),
    onSuccess: async (run) => {
      setSelectedRun(run);
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
    }
  });
  const rerunFailed = useMutation({
    mutationFn: (runId: number) => postJson<PipelineRun>(`/api/admin/runs/${runId}/rerun-failed`, {}),
    onSuccess: async (run) => {
      setSelectedRun(run);
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
    }
  });
  const deleteRun = useMutation({
    mutationFn: (runId: number) => deleteJson<Record<string, unknown>>(`/api/admin/runs/${runId}`),
    onSuccess: async (_payload, runId) => {
      if (selectedRun?.id === runId) {
        setSelectedRun(null);
      }
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      await queryClient.invalidateQueries({ queryKey: ["run-detail", runId] });
    }
  });

  return (
    <main className="pageShell">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Runs</p>
          <h1>Pipeline Batch Runs</h1>
        </div>
      </header>
      <section className="presetGrid">
        {(presets.data ?? []).map((preset) => (
          <article className="presetCard" key={preset.preset_key}>
            <h2>{preset.label}</h2>
            <p>{preset.description}</p>
            <div className="pathText">{preset.input_root}</div>
            <Button variant="primary" disabled={startRun.isPending} onClick={() => setSelectedPreset(preset)}>
              Configure
            </Button>
          </article>
        ))}
      </section>
      <section className="panel">
        <div className="sectionHeader">
          <h2>Run History</h2>
          <span>{runs.data?.length ?? 0} shown</span>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Role</th>
                <th>Preset</th>
                <th>Status</th>
                <th>Processed</th>
                <th>Started</th>
                <th>Output</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {(runs.data ?? []).map((run) => (
                <tr key={run.id}>
                  <td>
                    <Link className="linkButton" href={`/runs/${run.id}/report`}>
                      {run.run_key}
                    </Link>
                  </td>
                  <td>
                    <StatusBadge value={run.run_role ?? "test"} />
                  </td>
                  <td>{run.preset_key}</td>
                  <td>
                    <StatusBadge value={run.status} tone={run.status === "failed" ? "danger" : "default"} />
                  </td>
                  <td>{run.processed_count ?? "-"}</td>
                  <td>{run.started_at ?? run.created_at}</td>
                  <td className="pathText">{run.output_dir}</td>
                  <td>
                    <div className="buttonRow">
                      <button className="secondaryButton" disabled={run.status === "running"} onClick={() => importResults.mutate(run.id)}>
                        Import
                      </button>
                      <button
                        className="secondaryButton"
                        disabled={run.status !== "queued" && run.status !== "running"}
                        onClick={() => cancelRun.mutate(run.id)}
                      >
                        Cancel
                      </button>
                      <button className="secondaryButton" disabled={run.status !== "failed"} onClick={() => rerunFailed.mutate(run.id)}>
                        Rerun Failed
                      </button>
                      <button
                        className="secondaryButton dangerText"
                        disabled={run.status === "running" || deleteRun.isPending}
                        onClick={() => {
                          if (window.confirm(`Delete run ${run.run_key}? This removes dashboard DB rows and generated run artifacts, but not source corpus files.`)) {
                            deleteRun.mutate(run.id);
                          }
                        }}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {selectedPreset ? (
        <RunStartDialog
          preset={selectedPreset}
          starting={startRun.isPending}
          onClose={() => setSelectedPreset(null)}
          onStart={(body) => startRun.mutate(body)}
        />
      ) : null}
      {activeRun ? (
        <aside className="drawer">
          <div className="drawerHeader">
            <div>
              <p className="eyebrow">Run Details</p>
              <h2>{activeRun.run_key}</h2>
            </div>
            <Button onClick={() => setSelectedRun(null)}>
              Close
            </Button>
          </div>
          <div className="drawerGrid">
            <section>
              <h3>Status</h3>
              <div className="runStatusLine">
                {(activeRun.status === "running" || activeRun.status === "queued") ? <span className="spinner" aria-hidden="true" /> : null}
                <StatusBadge value={activeRun.status} tone={activeRun.status === "failed" ? "danger" : "default"} />
              </div>
              <RunProgressBar progress={progress.data} run={activeRun} />
              <KeyValue label="Preset" value={activeRun.preset_key} />
              <KeyValue label="Role" value={activeRun.run_role ?? "test"} />
              <KeyValue label="Processed" value={formatRunProgress(progress.data, activeRun)} />
              <KeyValue label="Started" value={activeRun.started_at ?? "-"} />
              <KeyValue label="Updated" value={progress.data?.updated_at ?? activeRun.updated_at ?? "-"} />
              <KeyValue label="Output" value={activeRun.output_dir ?? "-"} />
              <KeyValue label="Error" value={progress.data?.error ?? activeRun.error ?? "-"} />
              <a className="primaryButton" href={`/api/admin/runs/${activeRun.id}/results`} target="_blank">
                Open Results JSON
              </a>
            </section>
            <section>
              <h3>Result Preview</h3>
              <KeyValue label="Type" value={results.data?.result_type ?? "-"} />
              <KeyValue label="Rows" value={String(results.data?.results.length ?? 0)} />
              <pre className="jsonPreview">{JSON.stringify((results.data?.results ?? []).slice(0, 3), null, 2)}</pre>
            </section>
            <section className="wideSection">
              <h3>Diff vs Previous</h3>
              <div className="metrics compactMetrics">
                <MiniMetric label="Changed" value={comparison.data?.summary.changed ?? 0} />
                <MiniMetric label="Added" value={comparison.data?.summary.added ?? 0} />
                <MiniMetric label="Removed" value={comparison.data?.summary.removed ?? 0} />
              </div>
              <pre className="jsonPreview">{JSON.stringify((comparison.data?.changed ?? []).slice(0, 8), null, 2)}</pre>
            </section>
            <section className="wideSection">
              <h3>Live Log</h3>
              <div className="eventList">
                {(events.data ?? []).map((event) => (
                  <div key={event.id} className={event.level === "error" ? "eventRow errorEvent" : "eventRow"}>
                    <span>{event.timestamp}</span>
                    <strong>{event.level}{event.payload?.current ? ` ${String(event.payload.current)}/${String(event.payload.total ?? "?")}` : ""}</strong>
                    <p>{event.message}</p>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </aside>
      ) : null}
    </main>
  );
}

function RunStartDialog({
  preset,
  starting,
  onClose,
  onStart
}: {
  preset: RunPreset;
  starting: boolean;
  onClose: () => void;
  onStart: (body: Record<string, unknown>) => void;
}) {
  const [inputRoot, setInputRoot] = useState(preset.input_root);
  const [outputDir, setOutputDir] = useState(preset.output_dir);
  const [runRole, setRunRole] = useState("test");
  const [embeddingProvider, setEmbeddingProvider] = useState(preset.embedding_provider || "cortex");
  const [enableLlmTags, setEnableLlmTags] = useState(preset.enable_llm_tags);
  const [llmTagProvider, setLlmTagProvider] = useState(normalizeRunProvider(preset.llm_tag_provider));
  const [ocrFallbackProvider, setOcrFallbackProvider] = useState(normalizeRunProvider(preset.ocr_fallback_provider));
  const [semanticIndexPath, setSemanticIndexPath] = useState("");
  const [importOnSuccess, setImportOnSuccess] = useState(false);

  return (
    <aside className="drawer narrowDrawer">
      <div className="drawerHeader">
        <div>
          <p className="eyebrow">Start Run</p>
          <h2>{preset.label}</h2>
        </div>
        <Button onClick={onClose}>
          Close
        </Button>
      </div>
      <div className="formGrid runStartForm">
        <TextInput label="Input root" value={inputRoot} onChange={(event) => setInputRoot(event.target.value)} />
        <TextInput label="Output dir" value={outputDir} onChange={(event) => setOutputDir(event.target.value)} />
        <SelectInput label="Run role" value={runRole} onChange={(event) => setRunRole(event.target.value)}>
          <option value="test">Test</option>
          <option value="baseline">Baseline</option>
          <option value="evaluation">Evaluation</option>
        </SelectInput>
        <ProviderSelect label="Embedding path" value={embeddingProvider} onChange={setEmbeddingProvider} />
        <ProviderSelect label="LLM tag path" value={llmTagProvider} onChange={setLlmTagProvider} />
        <ProviderSelect label="OCR fallback path" value={ocrFallbackProvider} onChange={setOcrFallbackProvider} />
        <TextInput
          label="Semantic index path"
          value={semanticIndexPath}
          onChange={(event) => setSemanticIndexPath(event.target.value)}
          placeholder=".local/sunshine-semantic-index.sqlite"
        />
        <CheckboxField label="Enable LLM tags" checked={enableLlmTags} onChange={(event) => setEnableLlmTags(event.target.checked)} />
        <CheckboxField label="Import results on success" checked={importOnSuccess} onChange={(event) => setImportOnSuccess(event.target.checked)} />
        <Button
          variant="primary"
          disabled={starting}
          onClick={() =>
            onStart({
              preset_key: preset.preset_key,
              run_role: runRole,
              input_root: inputRoot,
              output_dir: outputDir,
              embedding_provider: embeddingProvider,
              enable_llm_tags: enableLlmTags,
              llm_tag_provider: llmTagProvider,
              ocr_fallback_provider: ocrFallbackProvider,
              semantic_index_path: semanticIndexPath || null,
              import_on_success: importOnSuccess
            })
          }
        >
          {starting ? "Starting..." : "Start Run"}
        </Button>
      </div>
    </aside>
  );
}

function MiniMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="miniMetric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function ProviderSelect({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="cortex">Cortex</option>
        <option value="openai">OpenAI</option>
      </select>
    </label>
  );
}

function normalizeRunProvider(value?: string | null) {
  return value === "openai" ? "openai" : "cortex";
}

function RunProgressBar({ progress, run }: { progress?: PipelineRunProgress; run: PipelineRun }) {
  const ratio = progress?.progress_ratio ?? (run.status === "succeeded" ? 1 : null);
  const percent = ratio == null ? null : Math.round(Math.max(0, Math.min(ratio, 1)) * 100);
  return (
    <div className="runProgress">
      <div className="progressTrack">
        <div className={percent == null ? "progressFill indeterminate" : "progressFill"} style={percent == null ? undefined : { width: `${percent}%` }} />
      </div>
      <span>{percent == null ? "Working..." : `${percent}%`}</span>
    </div>
  );
}

function formatRunProgress(progress: PipelineRunProgress | undefined, run: PipelineRun) {
  const processed = progress?.processed_count ?? run.processed_count;
  const total = progress?.total_count;
  if (processed == null && total == null) {
    return "-";
  }
  if (total == null) {
    return String(processed ?? "-");
  }
  return `${processed ?? 0} / ${total}`;
}
