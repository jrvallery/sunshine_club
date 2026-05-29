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

const FALLBACK_RUN_PRESETS: RunPreset[] = [
  {
    preset_key: "qa_samples_full",
    label: "QA samples full",
    description: "Full QA sample with LLM tags, OpenAI OCR fallback, and semantic examples.",
    input_root: "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples",
    output_dir: "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/dashboard-runs/qa_samples_full",
    enable_llm_tags: true,
    embedding_provider: "cortex",
    llm_tag_provider: "auto",
    ocr_fallback_provider: "openai"
  },
  {
    preset_key: "qa_samples_fast",
    label: "QA samples fast",
    description: "Fast QA regression pass without LLM tag inspection.",
    input_root: "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples",
    output_dir: "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/dashboard-runs/qa_samples_fast",
    enable_llm_tags: false,
    embedding_provider: "cortex",
    llm_tag_provider: "disabled",
    ocr_fallback_provider: "disabled"
  },
  {
    preset_key: "ocr_fallback_focus",
    label: "OCR fallback focus",
    description: "OCR-heavy QA sample with OpenAI OCR fallback for poor local OCR.",
    input_root: "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples",
    output_dir: "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/dashboard-runs/ocr_fallback_focus",
    enable_llm_tags: false,
    embedding_provider: "cortex",
    llm_tag_provider: "disabled",
    ocr_fallback_provider: "openai"
  },
  {
    preset_key: "review_required_rerun",
    label: "Review required rerun",
    description: "Rerun currently open review files after pipeline changes.",
    input_root: "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/review required files",
    output_dir: "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/dashboard-runs/review_required_rerun",
    enable_llm_tags: true,
    embedding_provider: "cortex",
    llm_tag_provider: "auto",
    ocr_fallback_provider: "openai"
  },
  {
    preset_key: "random_route_candidate_audit",
    label: "Route candidate audit",
    description: "Audit a random sample of auto-routed files after a run import.",
    input_root: "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples",
    output_dir: "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/dashboard-runs/random_route_candidate_audit",
    enable_llm_tags: true,
    embedding_provider: "cortex",
    llm_tag_provider: "auto",
    ocr_fallback_provider: "openai"
  },
  {
    preset_key: "single_file_debug",
    label: "Single file debug",
    description: "Debug one file by overriding input root/output parameters or using the file browser Run File action.",
    input_root: "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/qa samples",
    output_dir: "/mnt/sunshine/_manifest/sunshine-club-inventory-2026-05-25/dashboard-runs/single_file_debug",
    enable_llm_tags: false,
    embedding_provider: "cortex",
    llm_tag_provider: "disabled",
    ocr_fallback_provider: "disabled"
  }
];

export default function RunsPage() {
  const queryClient = useQueryClient();
  const source = "postgres";
  const [selectedRun, setSelectedRun] = useState<PipelineRun | null>(null);
  const [selectedPreset, setSelectedPreset] = useState<RunPreset | null>(null);
  const [quickStartPresetKey, setQuickStartPresetKey] = useState("");
  const presets = useQuery({ queryKey: ["run-presets"], queryFn: () => fetchJson<RunPreset[]>("/api/admin/runs/presets") });
  const availablePresets = presets.data?.length ? presets.data : FALLBACK_RUN_PRESETS;
  const quickStartPreset = availablePresets.find((preset) => preset.preset_key === quickStartPresetKey) ?? availablePresets[0] ?? null;
  const runs = useQuery({
    queryKey: ["runs", source],
    queryFn: () => fetchJson<PipelineRun[]>(`/api/admin/runs?limit=100&source=${source}`),
    refetchInterval: (query) => ((query.state.data ?? []).some((run) => run.status === "running" || run.status === "queued") ? 1500 : 5000)
  });
  const selectedRunDetail = useQuery({
    queryKey: ["run-detail", selectedRun?.id, source],
    enabled: Boolean(selectedRun) && selectedRun?.source !== "postgres",
    queryFn: () => fetchJson<PipelineRun>(`/api/admin/runs/${selectedRun?.id}`),
    refetchInterval: (query) => (query.state.data?.status === "running" || query.state.data?.status === "queued" ? 1500 : false)
  });
  const activeRun = selectedRunDetail.data ?? selectedRun;
  const progress = useQuery({
    queryKey: ["run-progress", selectedRun?.id, source],
    enabled: Boolean(selectedRun) && selectedRun?.source !== "postgres",
    queryFn: () => fetchJson<PipelineRunProgress>(`/api/admin/runs/${selectedRun?.id}/progress`),
    refetchInterval: activeRun?.status === "running" || activeRun?.status === "queued" ? 1500 : false
  });
  const events = useQuery({
    queryKey: ["run-events", selectedRun?.id, source],
    enabled: Boolean(selectedRun) && selectedRun?.source !== "postgres",
    queryFn: () => fetchJson<PipelineRunEvent[]>(`/api/admin/runs/${selectedRun?.id}/events`),
    refetchInterval: activeRun?.status === "running" || activeRun?.status === "queued" ? 1500 : false
  });
  const results = useQuery({
    queryKey: ["run-results", selectedRun?.id, source],
    enabled: Boolean(selectedRun) && selectedRun?.source !== "postgres",
    queryFn: () => fetchJson<PipelineRunResults>(`/api/admin/runs/${selectedRun?.id}/results`)
  });
  const comparison = useQuery({
    queryKey: ["run-comparison", selectedRun?.id, source],
    enabled: Boolean(selectedRun) && selectedRun?.source !== "postgres",
    queryFn: () => fetchJson<PipelineRunComparison>(`/api/admin/runs/${selectedRun?.id}/compare-previous`)
  });
  const startRun = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      postJson<PipelineRun>("/api/admin/runs", {
        start: true,
        import_on_success: true,
        ...payload
      }),
    onSuccess: async (run) => {
      setSelectedPreset(null);
      setSelectedRun(run);
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
    }
  });
  const importResults = useMutation({
    mutationFn: (run: PipelineRun) => postJson<Record<string, unknown>>(`${runActionBase(run)}/import-results`, {}),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
    }
  });
  const cancelRun = useMutation({
    mutationFn: (run: PipelineRun) => postJson<PipelineRun>(`${runActionBase(run)}/cancel`, {}),
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
    mutationFn: (run: PipelineRun) => deleteJson<Record<string, unknown>>(runActionBase(run)),
    onSuccess: async (_payload, run) => {
      if (selectedRun?.run_key === run.run_key) {
        setSelectedRun(null);
      }
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      await queryClient.invalidateQueries({ queryKey: ["run-detail", run.id] });
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
        {availablePresets.map((preset) => (
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
          <div>
            <h2>Run History</h2>
            <p className="muted">V2 Postgres runtime runs</p>
          </div>
          <div className="buttonRow">
            <SelectInput
              label="New run"
              value={quickStartPreset?.preset_key ?? ""}
              onChange={(event) => setQuickStartPresetKey(event.target.value)}
            >
              {availablePresets.map((preset) => (
                <option value={preset.preset_key} key={preset.preset_key}>
                  {preset.label}
                </option>
              ))}
            </SelectInput>
            <Button variant="primary" disabled={!quickStartPreset || startRun.isPending} onClick={() => quickStartPreset && setSelectedPreset(quickStartPreset)}>
              Configure Run
            </Button>
            <span className="pill">Postgres</span>
            <span>{runs.data?.length ?? 0} shown</span>
          </div>
        </div>
        <div className="tableWrap" tabIndex={0} aria-label="Run history table">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Role</th>
                <th>Preset</th>
                <th>Backend</th>
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
                    {source === "postgres" ? (
                      <Link className="linkButton" href={`/runs/${encodeURIComponent(run.run_key)}/report?source=postgres`}>
                        {run.run_key}
                      </Link>
                    ) : (
                      <Link className="linkButton" href={`/runs/${run.id}/report`}>
                        {run.run_key}
                      </Link>
                    )}
                  </td>
                  <td>
                    <StatusBadge value={run.run_role ?? "test"} />
                  </td>
                  <td>{run.preset_key}</td>
                  <td>{runExecutionBackend(run)}</td>
                  <td>
                    <StatusBadge value={run.status} tone={run.status === "failed" ? "danger" : "default"} />
                  </td>
                  <td>{run.processed_count ?? "-"}</td>
                  <td>{run.started_at ?? run.created_at}</td>
                  <td className="pathText">{run.output_dir}</td>
                  <td>
                    <div className="buttonRow">
                      <button className="secondaryButton" disabled={run.status === "running" || run.status === "queued"} onClick={() => importResults.mutate(run)}>
                        Import
                      </button>
                      <button
                        className="secondaryButton"
                        disabled={run.status !== "queued" && run.status !== "running"}
                        onClick={() => cancelRun.mutate(run)}
                      >
                        Cancel
                      </button>
                      <button
                        className="secondaryButton dangerText"
                        disabled={run.status === "running" || run.status === "queued" || deleteRun.isPending}
                        onClick={() => {
                          if (window.confirm(`Delete run ${run.run_key}? This removes dashboard DB rows and generated run artifacts, but not source corpus files.`)) {
                            deleteRun.mutate(run);
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
              <KeyValue label="Backend" value={runExecutionBackend(activeRun)} />
              <KeyValue label="Processed" value={formatRunProgress(progress.data, activeRun)} />
              <KeyValue label="Started" value={activeRun.started_at ?? "-"} />
              <KeyValue label="Updated" value={progress.data?.updated_at ?? activeRun.updated_at ?? "-"} />
              <KeyValue label="Output" value={activeRun.output_dir ?? "-"} />
              <KeyValue label="Error" value={progress.data?.error ?? activeRun.error ?? "-"} />
              <a className="primaryButton" href={`${runActionBase(activeRun)}/results`} target="_blank">
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
  const [embeddingProvider, setEmbeddingProvider] = useState(normalizeEmbeddingProvider(preset.embedding_provider));
  const [enableLlmTags, setEnableLlmTags] = useState(preset.enable_llm_tags);
  const [llmTagProvider, setLlmTagProvider] = useState(normalizeLlmProvider(preset.llm_tag_provider));
  const [ocrFallbackProvider, setOcrFallbackProvider] = useState(normalizeOcrProvider(preset.ocr_fallback_provider));
  const [semanticIndexPath, setSemanticIndexPath] = useState("");
  const [executionBackend, setExecutionBackend] = useState("subprocess");
  const [importOnSuccess, setImportOnSuccess] = useState(true);

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
        <ProviderSelect label="Embedding path" value={embeddingProvider} onChange={setEmbeddingProvider} options={["cortex", "placeholder"]} />
        <ProviderSelect label="LLM tag path" value={llmTagProvider} onChange={setLlmTagProvider} options={["cortex"]} />
        <ProviderSelect label="OCR fallback path" value={ocrFallbackProvider} onChange={setOcrFallbackProvider} options={["openai", "cortex", "disabled"]} />
        <ProviderSelect label="Execution backend" value={executionBackend} onChange={setExecutionBackend} options={["subprocess", "temporal"]} />
        <TextInput
          label="Semantic index path"
          value={semanticIndexPath}
          onChange={(event) => setSemanticIndexPath(event.target.value)}
          placeholder=".local/sunshine-semantic-index.sqlite"
        />
        <CheckboxField label="Enable LLM tags" checked={enableLlmTags} onChange={(event) => setEnableLlmTags(event.target.checked)} />
        <CheckboxField label="Auto-import review items on success" checked={importOnSuccess} onChange={(event) => setImportOnSuccess(event.target.checked)} />
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
              execution_backend: executionBackend,
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

function ProviderSelect({
  label,
  value,
  onChange,
  options
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: string[];
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option} value={option}>{providerLabel(option)}</option>
        ))}
      </select>
    </label>
  );
}

function providerLabel(value: string) {
  if (value === "openai") {
    return "OpenAI";
  }
  if (value === "subprocess") {
    return "Subprocess";
  }
  if (value === "temporal") {
    return "Temporal";
  }
  if (value === "placeholder") {
    return "Placeholder";
  }
  if (value === "disabled") {
    return "Disabled";
  }
  return "Cortex";
}

function runActionBase(run: PipelineRun) {
  if (run.source === "postgres") {
    return `/api/admin/runs/by-key/${encodeURIComponent(run.run_key)}`;
  }
  return `/api/admin/runs/${run.id}`;
}

function runExecutionBackend(run: PipelineRun) {
  const metadata = run.run_metadata ?? {};
  const backend = run.execution_backend ?? metadata.execution_backend;
  return typeof backend === "string" && backend ? backend : "subprocess";
}

function normalizeEmbeddingProvider(value?: string | null) {
  return value === "placeholder" ? "placeholder" : "cortex";
}

function normalizeLlmProvider(_value?: string | null) {
  return "cortex";
}

function normalizeOcrProvider(value?: string | null) {
  if (value === "openai") {
    return "openai";
  }
  return value === "disabled" ? "disabled" : "cortex";
}

function RunProgressBar({ progress, run }: { progress?: PipelineRunProgress; run: PipelineRun }) {
  const ratio = progress?.progress_ratio ?? (run.status === "succeeded" ? 1 : run.status === "failed" || run.status === "cancelled" ? 0 : null);
  const percent = ratio == null ? null : Math.round(Math.max(0, Math.min(ratio, 1)) * 100);
  const label = run.status === "failed" || run.status === "cancelled" ? "Stopped" : percent == null ? "Working..." : `${percent}%`;
  return (
    <div className="runProgress">
      <div className="progressTrack">
        <div className={percent == null ? "progressFill indeterminate" : "progressFill"} style={percent == null ? undefined : { width: `${percent}%` }} />
      </div>
      <span>{label}</span>
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
