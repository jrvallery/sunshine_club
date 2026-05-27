"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useMemo, useState } from "react";

import { PathCell } from "../../../../components/dashboard/PathCell";
import { ProviderConfigBadge } from "../../../../components/dashboard/ProviderConfigBadge";
import { QualityBadge } from "../../../../components/dashboard/QualityBadge";
import { RunContextBadge } from "../../../../components/dashboard/RunContextBadge";
import { KeyValue } from "../../../../components/ui/KeyValue";
import { StatusBadge } from "../../../../components/ui/StatusBadge";
import { deleteJson, fetchJson, postJson } from "../../../../lib/api";
import type { PipelineRun, PipelineRunEvent, RunModelUsageReport, RunReport } from "../../../../lib/types";

type ReportTab = "overview" | "files" | "review" | "training" | "ocr" | "tags" | "placement" | "models" | "logs" | "artifacts" | "diff";

const tabs: Array<{ key: ReportTab; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "files", label: "Files" },
  { key: "review", label: "Review Queue" },
  { key: "training", label: "Training Cycle" },
  { key: "ocr", label: "OCR" },
  { key: "tags", label: "Tags" },
  { key: "placement", label: "Placement" },
  { key: "models", label: "Model Usage" },
  { key: "logs", label: "Logs" },
  { key: "artifacts", label: "Artifacts" },
  { key: "diff", label: "Diff" }
];

export default function RunReportPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId: runIdParam } = use(params);
  const runId = Number(runIdParam);
  const [activeTab, setActiveTab] = useState<ReportTab>("overview");
  const queryClient = useQueryClient();
  const router = useRouter();
  const report = useQuery({
    queryKey: ["run-report", runId],
    queryFn: () => fetchJson<RunReport>(`/api/admin/runs/${runId}/report`),
    refetchInterval: (query) => (isActive(query.state.data?.run.status) ? 1500 : false)
  });
  const events = useQuery({
    queryKey: ["run-events", runId],
    queryFn: () => fetchJson<PipelineRunEvent[]>(`/api/admin/runs/${runId}/events?limit=300`),
    refetchInterval: isActive(report.data?.run.status) ? 1500 : false
  });
  const importResults = useMutation({
    mutationFn: () => postJson<Record<string, unknown>>(`/api/admin/runs/${runId}/import-results`, {}),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["run-report", runId] });
    }
  });
  const cancelRun = useMutation({
    mutationFn: () => postJson<PipelineRun>(`/api/admin/runs/${runId}/cancel`, {}),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["run-report", runId] });
      await queryClient.invalidateQueries({ queryKey: ["run-events", runId] });
    }
  });
  const deleteRun = useMutation({
    mutationFn: () => deleteJson<Record<string, unknown>>(`/api/admin/runs/${runId}`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      router.push("/runs");
    }
  });
  const data = report.data;
  const run = data?.run;
  const running = isActive(run?.status);
  const modelSummary = data?.model_usage.summary;
  const fileRows = useMemo(() => data?.files ?? [], [data?.files]);

  if (report.isLoading) {
    return <main className="pageShell"><div className="empty">Loading run report...</div></main>;
  }

  if (!data || !run) {
    return (
      <main className="pageShell">
        <div className="empty">Run report was not found.</div>
      </main>
    );
  }

  return (
    <main className="pageShell">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Run Report</p>
          <h1>{run.run_key}</h1>
          <p className="muted">{run.input_root}</p>
        </div>
        <div className="buttonRow">
          <Link className="secondaryButton" href="/runs">Back to Runs</Link>
          <Link className="secondaryButton" href={`/review?run_id=${run.id}&status=all`}>Review This Run</Link>
          <button className="secondaryButton" disabled={run.status === "running" || importResults.isPending} onClick={() => importResults.mutate()}>
            {importResults.isPending ? "Importing..." : "Import Results"}
          </button>
          <button className="secondaryButton" disabled={!running || cancelRun.isPending} onClick={() => cancelRun.mutate()}>
            {cancelRun.isPending ? "Cancelling..." : "Cancel"}
          </button>
          <button
            className="secondaryButton dangerText"
            disabled={running || deleteRun.isPending}
            onClick={() => {
              if (window.confirm(`Delete run ${run.run_key}? This removes dashboard DB rows and generated run artifacts, but not source corpus files.`)) {
                deleteRun.mutate();
              }
            }}
          >
            {deleteRun.isPending ? "Deleting..." : "Delete"}
          </button>
        </div>
      </header>

      <section className="panel runReportHeader">
        <div>
          <div className="runStatusLine">
            {running ? <span className="spinner" aria-hidden="true" /> : null}
            <StatusBadge value={run.status} tone={run.status === "failed" ? "danger" : "default"} />
          </div>
          {running ? <RunProgressBar report={data} /> : null}
        </div>
        <div className="runMetaGrid">
          <KeyValue label="Run" value={<RunContextBadge runId={run.id} runKey={run.run_key} preset={run.preset_key} />} />
          <KeyValue label="Preset" value={run.preset_key} />
          <KeyValue label="Role" value={run.run_role ?? "test"} />
          <KeyValue label="Started" value={run.started_at ?? "-"} />
          <KeyValue label="Completed" value={run.completed_at ?? "-"} />
          <KeyValue label="Output" value={run.output_dir ?? "-"} />
          <KeyValue
            label="Providers"
            value={
              <ProviderConfigBadge
                embeddingProvider={run.embedding_provider}
                llmEnabled={run.enable_llm_tags}
                llmProvider={run.llm_tag_provider}
                ocrProvider={run.ocr_fallback_provider}
              />
            }
          />
          <KeyValue label="Error" value={data.progress.error ?? run.error ?? "-"} />
        </div>
      </section>

      <section className="metrics">
        <Metric label="Processed" value={formatProcessed(data)} />
        <Metric label="Review required" value={String(data.overview.review_required_count ?? 0)} />
        <Metric label="Failed" value={String(data.overview.failed_count ?? 0)} />
        <Metric label="Model calls" value={String(modelSummary?.total_calls ?? 0)} />
        <Metric label="External cost" value={formatCost(modelSummary?.estimated_external_cost_usd ?? 0)} />
      </section>

      <nav className="tabBar" aria-label="Run report sections">
        {tabs.map((tab) => (
          <button className={activeTab === tab.key ? "tabButton active" : "tabButton"} key={tab.key} onClick={() => setActiveTab(tab.key)}>
            {tab.label}
          </button>
        ))}
      </nav>

      {activeTab === "overview" ? <OverviewTab report={data} /> : null}
      {activeTab === "files" ? <FilesTab rows={fileRows} /> : null}
      {activeTab === "review" ? <ReviewQueueTab report={data} /> : null}
      {activeTab === "training" ? <TrainingCycleTab report={data} /> : null}
      {activeTab === "ocr" ? <OcrTab report={data} /> : null}
      {activeTab === "tags" ? <BreakdownGrid values={data.tags} /> : null}
      {activeTab === "placement" ? <BreakdownGrid values={data.placement} /> : null}
      {activeTab === "models" ? <ModelUsageTab usage={data.model_usage} /> : null}
      {activeTab === "logs" ? <LogsTab events={events.data ?? []} /> : null}
      {activeTab === "artifacts" ? <ArtifactsTab report={data} /> : null}
      {activeTab === "diff" ? <DiffTab report={data} /> : null}
    </main>
  );
}

function OverviewTab({ report }: { report: RunReport }) {
  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>Run Overview</h2>
      </div>
      <div className="reportGrid">
        <Breakdown title="Routes" values={report.distributions.route_status ?? {}} />
        <Breakdown title="Quality" values={report.distributions.quality ?? {}} />
        <Breakdown title="Content Class" values={report.distributions.final_class ?? {}} />
        <Breakdown title="Warnings" values={report.distributions.warnings ?? {}} />
      </div>
      <pre className="jsonPreview">{JSON.stringify(report.overview.summary ?? {}, null, 2)}</pre>
    </section>
  );
}

function FilesTab({ rows }: { rows: Array<Record<string, unknown>> }) {
  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>Files</h2>
        <span>{rows.length} shown</span>
      </div>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>Class</th>
              <th>Tag</th>
              <th>Quality</th>
              <th>Route</th>
              <th>Snippet</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${String(row.source_path ?? index)}`}>
                <td><PathCell title={String(row.relative_path ?? row.source_path ?? "-")} /></td>
                <td>{String(row.final_class ?? "-")}</td>
                <td>{String(row.top_tag_candidate ?? "-")}</td>
                <td><QualityBadge value={String(row.quality ?? "-")} /></td>
                <td>{String(row.route_status ?? "-")}</td>
                <td className="snippetCell">{String(row.extraction_text_snippet ?? "-")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function OcrTab({ report }: { report: RunReport }) {
  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>OCR</h2>
        <span>{report.ocr.document_count} documents, {report.ocr.page_count} pages</span>
      </div>
      <JsonTable title="OCR Documents" rows={report.ocr.documents} />
    </section>
  );
}

function ModelUsageTab({ usage }: { usage: RunModelUsageReport }) {
  return (
    <section className="panel">
      <div className="metrics compactMetrics">
        <Metric label="Calls" value={String(usage.summary.total_calls)} />
        <Metric label="Failures" value={String(usage.summary.failed_calls)} />
        <Metric label="Tokens" value={String(usage.summary.total_tokens)} />
        <Metric label="Runtime" value={formatMs(usage.summary.runtime_ms)} />
        <Metric label="External cost" value={formatCost(usage.summary.estimated_external_cost_usd)} />
      </div>
      <div className="reportGrid">
        <UsageBreakdown title="Provider / Model" values={usage.by_provider_model} />
        <UsageBreakdown title="Purpose" values={usage.by_purpose} />
      </div>
      <JsonTable title="Model Calls" rows={usage.calls} />
    </section>
  );
}

function ReviewQueueTab({ report }: { report: RunReport }) {
  const links = report.review_queue.links ?? {};
  return (
    <section className="panel">
      <div className="sectionHeader">
        <div>
          <h2>Review Queue</h2>
          <span>{report.review_queue.count} review items linked to this run</span>
        </div>
        <div className="buttonRow">
          <Link className="secondaryButton" href={links.open ?? `/review?run_id=${report.run.id}&status=open`}>Open Items</Link>
          <Link className="secondaryButton" href={links.all ?? `/review?run_id=${report.run.id}&status=all`}>All Items</Link>
          <Link className="secondaryButton" href={links.ocr ?? `/review?run_id=${report.run.id}&status=all&review_reason=ocr_quality_not_trusted`}>OCR Issues</Link>
          <Link className="secondaryButton" href={links.tag_disagreements ?? `/review?run_id=${report.run.id}&status=all&review_reason=llm_tag_disagreement`}>Tag Disagreements</Link>
          <Link className="secondaryButton" href={links.low_confidence ?? `/review?run_id=${report.run.id}&status=all&review_reason=tag_confidence_below_threshold`}>Low Confidence</Link>
          <Link className="secondaryButton" href={links.placement ?? `/review?run_id=${report.run.id}&status=all&placement_status=needs_review`}>Placement Issues</Link>
        </div>
      </div>
      <div className="metrics compactMetrics">
        {Object.entries(report.review_queue.by_status ?? {}).map(([status, count]) => (
          <Metric key={status} label={status} value={String(count)} />
        ))}
        {!Object.keys(report.review_queue.by_status ?? {}).length ? <Metric label="Status" value="-" /> : null}
      </div>
      <ReviewItemRows runId={report.run.id} rows={report.review_queue.items} />
    </section>
  );
}

function ReviewItemRows({ runId, rows }: { runId: number; rows: Array<Record<string, unknown>> }) {
  return (
    <div className="jsonTableBlock">
      <div className="sectionHeader">
        <h2>Review Items</h2>
        <span>{rows.length} shown</span>
      </div>
      {!rows.length ? <div className="empty">No review items imported for this run.</div> : null}
      {rows.length ? (
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Status</th>
                <th>Reason</th>
                <th>Class</th>
                <th>Tag</th>
                <th>Quality</th>
                <th>Review</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => {
                const relativePath = String(row.relative_path ?? row.source_path ?? "-");
                return (
                  <tr key={String(row.id ?? row.source_path ?? index)}>
                    <td><PathCell title={relativePath} /></td>
                    <td>{String(row.status ?? row.route_status ?? "-")}</td>
                    <td>{String(row.review_reason ?? "-")}</td>
                    <td>{String(row.proposed_class ?? row.final_class ?? "-")}</td>
                    <td>{String(row.proposed_tag ?? row.top_tag_candidate ?? "-")}</td>
                    <td><QualityBadge value={String((row.result as Record<string, unknown> | undefined)?.quality ?? row.quality ?? "-")} /></td>
                    <td>
                      <Link className="viewLink" href={`/review?run_id=${runId}&status=all&q=${encodeURIComponent(relativePath)}`}>
                        Open
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function TrainingCycleTab({ report }: { report: RunReport }) {
  const metrics = report.training_cycle ?? {};
  return (
    <section className="panel">
      <div className="sectionHeader">
        <div>
          <h2>Training Cycle</h2>
          <span>Review, correction, golden-label, and run-to-run movement for this run.</span>
        </div>
        <div className="buttonRow">
          <Link className="secondaryButton" href={`/review?run_id=${report.run.id}&status=all`}>Review This Run</Link>
          <Link className="secondaryButton" href="/golden-labels">Golden Labels</Link>
        </div>
      </div>
      <div className="metrics compactMetrics">
        <Metric label="Processed" value={metricValue(metrics.files_processed)} />
        <Metric label="Review required" value={metricValue(metrics.review_required_count)} />
        <Metric label="Open review" value={metricValue(metrics.open_review_count)} />
        <Metric label="Resolved" value={metricValue(metrics.resolved_review_count)} />
        <Metric label="Accepted" value={metricValue(metrics.accepted_count)} />
        <Metric label="Corrected" value={metricValue(metrics.corrected_count)} />
        <Metric label="Golden labels" value={metricValue(metrics.golden_labels_created)} />
        <Metric label="OCR failures" value={metricValue(metrics.ocr_failure_count)} />
        <Metric label="Tag disagreements" value={metricValue(metrics.tag_disagreement_count)} />
        <Metric label="Review rate" value={formatRatio(metrics.review_rate)} />
        <Metric label="OCR failure rate" value={formatRatio(metrics.ocr_failure_rate)} />
        <Metric label="Resolution rate" value={formatRatio(metrics.resolution_rate)} />
        <Metric label="Correction rate" value={formatRatio(metrics.correction_rate)} />
        <Metric label="Reviewed accuracy" value={formatRatio(metrics.reviewed_primary_accuracy)} />
        <Metric label="Golden accuracy" value={formatRatio(metrics.golden_primary_accuracy)} />
        <Metric label="Secondary precision" value={formatRatio(metrics.secondary_precision)} />
        <Metric label="Secondary recall" value={formatRatio(metrics.secondary_recall)} />
        <Metric label="Run changes" value={metricValue(metrics.run_to_run_changed_count)} />
      </div>
      <pre className="jsonPreview">{JSON.stringify(metrics, null, 2)}</pre>
    </section>
  );
}

function metricValue(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return String(value);
}

function formatRatio(value: unknown) {
  if (typeof value !== "number") {
    return "-";
  }
  return `${Math.round(value * 1000) / 10}%`;
}

function LogsTab({ events }: { events: PipelineRunEvent[] }) {
  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>Run Logs</h2>
        <span>{events.length} events</span>
      </div>
      <div className="eventList">
        {events.map((event) => (
          <div key={event.id} className={event.level === "error" ? "eventRow errorEvent" : "eventRow"}>
            <span>{event.timestamp}</span>
            <strong>{event.level}{event.payload?.current ? ` ${String(event.payload.current)}/${String(event.payload.total ?? "?")}` : ""}</strong>
            <p>{event.message}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function ArtifactsTab({ report }: { report: RunReport }) {
  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>Artifacts</h2>
      </div>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Exists</th>
              <th>Rows</th>
              <th>Size</th>
              <th>Path</th>
            </tr>
          </thead>
          <tbody>
            {report.artifacts.map((artifact) => (
              <tr key={artifact.name}>
                <td>{artifact.name}</td>
                <td>{artifact.exists ? "yes" : "no"}</td>
                <td>{artifact.row_count ?? "-"}</td>
                <td>{artifact.size_bytes ?? "-"}</td>
                <td className="pathText">{artifact.path}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function DiffTab({ report }: { report: RunReport }) {
  return (
    <section className="panel">
      <div className="metrics compactMetrics">
        <Metric label="Changed" value={String(report.diff.summary.changed ?? 0)} />
        <Metric label="Added" value={String(report.diff.summary.added ?? 0)} />
        <Metric label="Removed" value={String(report.diff.summary.removed ?? 0)} />
        <Metric label="Previous run" value={String(report.diff.previous_run_id ?? "-")} />
      </div>
      <JsonTable title="Changed Files" rows={report.diff.changed} />
    </section>
  );
}

function JsonTable({ title, rows }: { title: string; rows: Array<Record<string, unknown>> }) {
  return (
    <div className="jsonTableBlock">
      <div className="sectionHeader">
        <h2>{title}</h2>
        <span>{rows.length} shown</span>
      </div>
      {rows.length ? <pre className="jsonPreview">{JSON.stringify(rows.slice(0, 100), null, 2)}</pre> : <div className="empty">No data for this section.</div>}
    </div>
  );
}

function BreakdownGrid({ values }: { values: Record<string, Record<string, number>> }) {
  return (
    <section className="panel">
      <div className="reportGrid">
        {Object.entries(values).map(([title, counts]) => (
          <Breakdown title={title} values={counts} key={title} />
        ))}
      </div>
    </section>
  );
}

function Breakdown({ title, values }: { title: string; values: Record<string, number> }) {
  return (
    <div className="breakdown">
      <h2>{title}</h2>
      {Object.entries(values).map(([label, count]) => (
        <div className="breakdownRow" key={label}>
          <span>{label}</span>
          <strong>{count}</strong>
        </div>
      ))}
      {!Object.keys(values).length ? <p className="muted">No data yet.</p> : null}
    </div>
  );
}

function UsageBreakdown({ title, values }: { title: string; values: Record<string, Record<string, number>> }) {
  return (
    <div className="breakdown">
      <h2>{title}</h2>
      {Object.entries(values).map(([label, row]) => (
        <div className="breakdownRow stacked" key={label}>
          <span>{label}</span>
          <strong>{row.calls ?? 0} calls, {row.total_tokens ?? 0} tokens, {formatMs(row.runtime_ms ?? 0)}</strong>
        </div>
      ))}
      {!Object.keys(values).length ? <p className="muted">No model calls recorded.</p> : null}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <div className="metricValue">{value}</div>
      <div className="metricLabel">{label}</div>
    </div>
  );
}

function RunProgressBar({ report }: { report: RunReport }) {
  const ratio = report.progress.progress_ratio ?? null;
  const percent = ratio == null ? null : Math.round(Math.max(0, Math.min(ratio, 1)) * 100);
  return (
    <div className="runProgress">
      <div className="progressTrack">
        <div className={percent == null ? "progressFill indeterminate" : "progressFill"} style={percent == null ? undefined : { width: `${percent}%` }} />
      </div>
      <span>{percent == null ? "Working..." : `${percent}%`} {formatProcessed(report)}</span>
    </div>
  );
}

function formatProcessed(report: RunReport) {
  const processed = report.progress.processed_count ?? report.run.processed_count ?? report.overview.processed_count ?? 0;
  const total = report.progress.total_count;
  return total == null ? String(processed) : `${processed} / ${total}`;
}

function formatCost(value: number) {
  return value > 0 ? `$${value.toFixed(4)}` : "$0";
}

function formatMs(value: number) {
  if (!value) {
    return "-";
  }
  if (value < 1000) {
    return `${value} ms`;
  }
  return `${Math.round(value / 100) / 10}s`;
}

function isActive(status?: string) {
  return status === "queued" || status === "running";
}
