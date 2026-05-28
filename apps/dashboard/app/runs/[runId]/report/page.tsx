"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { use, useMemo, useState } from "react";

import { PathCell } from "../../../../components/dashboard/PathCell";
import { ProviderConfigBadge } from "../../../../components/dashboard/ProviderConfigBadge";
import { QualityBadge } from "../../../../components/dashboard/QualityBadge";
import { RunContextBadge } from "../../../../components/dashboard/RunContextBadge";
import { KeyValue } from "../../../../components/ui/KeyValue";
import { StatusBadge } from "../../../../components/ui/StatusBadge";
import { deleteJson, fetchJson, postJson } from "../../../../lib/api";
import type { PipelineRun, PipelineRunEvent, PostgresRunReport, RunModelUsageReport, RunReport } from "../../../../lib/types";

type ReportTab = "overview" | "files" | "review" | "segments" | "training" | "ocr" | "tags" | "placement" | "models" | "logs" | "artifacts" | "diff";

const tabs: Array<{ key: ReportTab; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "files", label: "Files" },
  { key: "review", label: "Review Queue" },
  { key: "segments", label: "Segments" },
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
  const searchParams = useSearchParams();
  const postgresMode = searchParams.get("source") === "postgres" || Number.isNaN(runId);
  const [activeTab, setActiveTab] = useState<ReportTab>("overview");
  const queryClient = useQueryClient();
  const router = useRouter();
  const report = useQuery({
    queryKey: ["run-report", runId],
    enabled: !postgresMode,
    queryFn: () => fetchJson<RunReport>(`/api/admin/runs/${runId}/report`),
    refetchInterval: (query) => (isActive(query.state.data?.run.status) ? 1500 : false)
  });
  const data = report.data;
  const postgresRunKey = postgresMode ? runIdParam : data?.run.run_key;
  const postgresReport = useQuery({
    queryKey: ["postgres-run-report", postgresRunKey],
    enabled: Boolean(postgresRunKey),
    queryFn: () => fetchJson<PostgresRunReport>(`/api/admin/system/postgres-runtime/runs/${encodeURIComponent(String(postgresRunKey))}/report`),
    retry: false,
    refetchInterval: postgresMode ? 5000 : isActive(data?.run.status) ? 1500 : false
  });
  const events = useQuery({
    queryKey: ["run-events", runId],
    enabled: !postgresMode,
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
  const run = data?.run;
  const running = isActive(run?.status);
  const modelSummary = data?.model_usage?.summary;
  const postgresData = postgresReport.data;
  const fileRows = useMemo(() => (postgresData?.results?.length ? postgresData.results : data?.files ?? []), [data?.files, postgresData?.results]);
  const logRows = postgresData?.run_events?.length ? postgresData.run_events : events.data ?? [];

  if (postgresMode) {
    if (postgresReport.isLoading) {
      return <RunReportLoading />;
    }
    if (!postgresData) {
      return (
        <main className="pageShell">
          <header className="pageHeader">
            <div>
              <p className="eyebrow">Postgres V2 Run Report</p>
              <h1>Run Report Not Found</h1>
              <p className="muted">{runIdParam}</p>
            </div>
            <Link className="secondaryButton" href="/runs">Back to Runs</Link>
          </header>
          <div className="empty">{postgresReport.error ? postgresReport.error.message : "Postgres V2 run report was not found."}</div>
        </main>
      );
    }
    return (
      <PostgresRunReportView
        report={postgresData}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
      />
    );
  }

  if (report.isLoading) {
    return <RunReportLoading />;
  }

  if (!data || !run) {
    return (
      <main className="pageShell">
        <header className="pageHeader">
          <div>
            <p className="eyebrow">Run Report</p>
            <h1>Run Report Not Found</h1>
          </div>
          <Link className="secondaryButton" href="/runs">Back to Runs</Link>
        </header>
        <div className="empty">Run report was not found.</div>
      </main>
    );
  }

  const statusBuckets = data.status_buckets ?? (data.overview.status_buckets as Record<string, number> | undefined) ?? {};

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
          <KeyValue label="Backend" value={runExecutionBackend(run)} />
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
        <Metric label="Accepted" value={String(statusBuckets.accepted ?? 0)} />
        <Metric label="Review required" value={String(data.overview.review_required_count ?? 0)} />
        <Metric label="Failed" value={String(data.overview.failed_count ?? 0)} />
        <Metric label="Deferred" value={String(statusBuckets.deferred ?? 0)} />
        <Metric label="Model calls" value={String(modelSummary?.total_calls ?? 0)} />
        <Metric label="Segment reviews" value={String(postgresData?.summary.segment_review_count ?? 0)} />
        <Metric label="Graph events" value={String(postgresData?.summary.run_event_count ?? events.data?.length ?? 0)} />
        <Metric label="External cost" value={formatCost(modelSummary?.estimated_external_cost_usd ?? 0)} />
      </section>

      <nav className="tabBar" aria-label="Run report sections">
        {tabs.map((tab) => (
          <button className={activeTab === tab.key ? "tabButton active" : "tabButton"} key={tab.key} onClick={() => setActiveTab(tab.key)}>
            {tab.label}
          </button>
        ))}
      </nav>

      {activeTab === "overview" ? <OverviewTab report={data} postgresReport={postgresData} postgresError={postgresReport.error} /> : null}
      {activeTab === "files" ? <FilesTab rows={fileRows} /> : null}
      {activeTab === "review" ? <ReviewQueueTab report={data} postgresReport={postgresData} /> : null}
      {activeTab === "segments" ? <SegmentsTab postgresReport={postgresData} postgresError={postgresReport.error} /> : null}
      {activeTab === "training" ? <TrainingCycleTab report={data} /> : null}
      {activeTab === "ocr" ? <OcrTab report={data} /> : null}
      {activeTab === "tags" ? <BreakdownGrid values={data.tags} /> : null}
      {activeTab === "placement" ? <BreakdownGrid values={data.placement} /> : null}
      {activeTab === "models" ? <ModelUsageTab usage={data.model_usage} /> : null}
      {activeTab === "logs" ? <LogsTab events={logRows} postgresBacked={Boolean(postgresData?.run_events?.length)} /> : null}
      {activeTab === "artifacts" ? <ArtifactsTab report={data} /> : null}
      {activeTab === "diff" ? <DiffTab report={data} /> : null}
    </main>
  );
}

function RunReportLoading() {
  return (
    <main className="pageShell">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Run Report</p>
          <h1>Loading Run Report</h1>
        </div>
      </header>
      <div className="empty">Loading run report...</div>
    </main>
  );
}

function PostgresRunReportView({
  report,
  activeTab,
  setActiveTab
}: {
  report: PostgresRunReport;
  activeTab: ReportTab;
  setActiveTab: (tab: ReportTab) => void;
}) {
  const runKey = String(report.run.run_key ?? "");
  const status = String(report.run.status ?? "-");
  const modelCalls = Number(report.summary.model_call_count ?? 0);
  const postgresTabs = tabs.filter((tab) => ["overview", "files", "review", "segments", "ocr", "models", "logs"].includes(tab.key));
  const activePostgresTab = postgresTabs.some((tab) => tab.key === activeTab) ? activeTab : "overview";
  return (
    <main className="pageShell">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Postgres V2 Run Report</p>
          <h1>{runKey}</h1>
          <p className="muted">{String(report.run.input_root ?? "")}</p>
        </div>
        <div className="buttonRow">
          <Link className="secondaryButton" href="/runs">Back to Runs</Link>
          <a className="secondaryButton" href={`/api/admin/system/postgres-runtime/runs/${encodeURIComponent(runKey)}/report`} target="_blank">
            Open JSON
          </a>
        </div>
      </header>

      <section className="panel runReportHeader">
        <div className="runStatusLine">
          {isActive(status) ? <span className="spinner" aria-hidden="true" /> : null}
          <StatusBadge value={status} tone={status === "failed" ? "danger" : "default"} />
        </div>
        <div className="runMetaGrid">
          <KeyValue label="Run" value={<RunContextBadge runId={runKey} runKey={runKey} preset={String(report.run.preset_key ?? "-")} />} />
          <KeyValue label="Preset" value={String(report.run.preset_key ?? "-")} />
          <KeyValue label="Source" value="Postgres V2" />
          <KeyValue label="Backend" value={postgresExecutionBackend(report)} />
          <KeyValue label="Started" value={String(report.run.started_at ?? "-")} />
          <KeyValue label="Completed" value={String(report.run.finished_at ?? "-")} />
          <KeyValue label="Output" value={String(report.run.output_dir ?? "-")} />
        </div>
      </section>

      <section className="metrics">
        <Metric label="Results" value={String(report.summary.result_count ?? 0)} />
        <Metric label="Review items" value={String(report.summary.review_item_count ?? 0)} />
        <Metric label="Open review" value={String(report.summary.open_review_item_count ?? 0)} />
        <Metric label="Segments" value={String(report.summary.document_segment_count ?? 0)} />
        <Metric label="Segment reviews" value={String(report.summary.segment_review_count ?? 0)} />
        <Metric label="Parser results" value={String(report.summary.parser_result_count ?? report.parser_results?.length ?? 0)} />
        <Metric label="Parser review" value={String(report.summary.parser_review_required_count ?? 0)} />
        <Metric label="Model calls" value={String(modelCalls)} />
        <Metric label="Provider attempts" value={String(report.summary.provider_attempt_count ?? 0)} />
        <Metric label="Graph events" value={String(report.summary.run_event_count ?? 0)} />
      </section>

      <nav className="tabBar" aria-label="Postgres run report sections">
        {postgresTabs.map((tab) => (
          <button className={activePostgresTab === tab.key ? "tabButton active" : "tabButton"} key={tab.key} onClick={() => setActiveTab(tab.key)}>
            {tab.label}
          </button>
        ))}
      </nav>

      {activePostgresTab === "overview" ? <PostgresOverviewTab report={report} /> : null}
      {activePostgresTab === "files" ? <FilesTab rows={report.results ?? []} /> : null}
      {activePostgresTab === "review" ? <PostgresReviewQueueTab report={report} /> : null}
      {activePostgresTab === "segments" ? <SegmentsTab postgresReport={report} /> : null}
      {activePostgresTab === "ocr" ? <PostgresParserTab report={report} /> : null}
      {activePostgresTab === "models" ? <JsonTable title="Model Calls" rows={report.model_usage ?? []} /> : null}
      {activePostgresTab === "logs" ? <LogsTab events={report.run_events ?? []} postgresBacked /> : null}
    </main>
  );
}

function PostgresOverviewTab({ report }: { report: PostgresRunReport }) {
  return (
    <section className="panel">
      <div className="reportGrid">
        <Breakdown title="Routes" values={report.summary.route_status ?? {}} />
        <Breakdown title="Quality" values={report.summary.quality ?? {}} />
        <Breakdown title="Primary Tags" values={report.summary.primary_tag ?? {}} />
        <Breakdown title="Segment Types" values={report.summary.segment_type ?? {}} />
        <Breakdown title="Provider Attempts" values={report.summary.provider_attempt_status ?? {}} />
        <Breakdown title="Parser Quality" values={report.summary.parser_quality ?? {}} />
        <Breakdown title="Parser Providers" values={report.summary.parser_provider ?? {}} />
        <Breakdown title="Graph Events" values={report.summary.run_event_status ?? {}} />
      </div>
    </section>
  );
}

function PostgresParserTab({ report }: { report: PostgresRunReport }) {
  const rows = report.parser_results ?? [];
  return (
    <section className="panel">
      <div className="sectionHeader">
        <div>
          <h2>Parser Results</h2>
          <span>{rows.length} parser/OCR rows imported for this run</span>
        </div>
      </div>
      <div className="metrics compactMetrics">
        <Metric label="Rows" value={String(report.summary.parser_result_count ?? rows.length)} />
        <Metric label="Needs review" value={String(report.summary.parser_review_required_count ?? 0)} />
      </div>
      <div className="reportGrid">
        <Breakdown title="Parser Status" values={report.summary.parser_status ?? {}} />
        <Breakdown title="Parser Quality" values={report.summary.parser_quality ?? {}} />
        <Breakdown title="Parser Provider" values={report.summary.parser_provider ?? {}} />
      </div>
      <JsonTable title="Parser Rows" rows={rows} />
    </section>
  );
}

function PostgresReviewQueueTab({ report }: { report: PostgresRunReport }) {
  return (
    <section className="panel">
      <div className="sectionHeader">
        <div>
          <h2>Review Queue</h2>
          <span>{report.review_items.length} Postgres V2 review items</span>
        </div>
        <Link className="secondaryButton" href={`/review?source=postgres&run_key=${encodeURIComponent(String(report.run.run_key ?? ""))}&status=all`}>
          Open In Review
        </Link>
      </div>
      <ReviewItemRows runId={String(report.run.run_key ?? "")} rows={report.review_items} />
    </section>
  );
}

function OverviewTab({ report, postgresReport, postgresError }: { report: RunReport; postgresReport?: PostgresRunReport; postgresError?: Error | null }) {
  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>Run Overview</h2>
      </div>
      <PostgresRuntimeSummary postgresReport={postgresReport} postgresError={postgresError} />
      <div className="reportGrid">
        <Breakdown title="Production Buckets" values={report.status_buckets ?? {}} />
        <Breakdown title="Routes" values={report.distributions.route_status ?? {}} />
        <Breakdown title="Quality" values={report.distributions.quality ?? {}} />
        <Breakdown title="Content Class" values={report.distributions.final_class ?? {}} />
        <Breakdown title="Warnings" values={report.distributions.warnings ?? {}} />
      </div>
      <pre className="jsonPreview" tabIndex={0} aria-label="Run overview summary JSON">{JSON.stringify(report.overview.summary ?? {}, null, 2)}</pre>
    </section>
  );
}

function PostgresRuntimeSummary({ postgresReport, postgresError }: { postgresReport?: PostgresRunReport; postgresError?: Error | null }) {
  if (postgresReport) {
    return (
      <div className="runtimeCallout">
        <div>
          <strong>Postgres V2 runtime</strong>
          <p className="muted">Normalized run report is available from Postgres. Segment proposals and model/provider rows below come from the V2 tables.</p>
        </div>
        <div className="metrics compactMetrics">
          <Metric label="PG results" value={String(postgresReport.summary.result_count)} />
          <Metric label="PG review" value={String(postgresReport.summary.open_review_item_count)} />
          <Metric label="Segments" value={String(postgresReport.summary.document_segment_count)} />
          <Metric label="Segment review" value={String(postgresReport.summary.segment_review_count)} />
          <Metric label="Graph events" value={String(postgresReport.summary.run_event_count ?? 0)} />
          <Metric label="Failed nodes" value={String(postgresReport.summary.failed_run_event_count ?? 0)} />
          <Metric label="Local calls" value={String(postgresReport.summary.local_model_call_count)} />
          <Metric label="Nonlocal calls" value={String(postgresReport.summary.nonlocal_model_call_count)} />
        </div>
      </div>
    );
  }
  return (
    <div className="runtimeCallout muted">
      <strong>Postgres V2 runtime unavailable</strong>
      <p>{postgresError ? postgresError.message : "Import this run into Postgres to inspect normalized results, model usage, provider attempts, and document segments."}</p>
    </div>
  );
}

function FilesTab({ rows }: { rows: Array<Record<string, unknown>> }) {
  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>Files</h2>
        <span>{rows.length} shown</span>
      </div>
      <div className="tableWrap" tabIndex={0} aria-label="Run files table">
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

function ReviewQueueTab({ report, postgresReport }: { report: RunReport; postgresReport?: PostgresRunReport }) {
  const links = report.review_queue.links ?? {};
  const rows = postgresReport?.review_items?.length ? postgresReport.review_items : report.review_queue.items;
  const rowCount = postgresReport?.review_items?.length ?? report.review_queue.count;
  return (
    <section className="panel">
      <div className="sectionHeader">
        <div>
          <h2>Review Queue</h2>
          <span>{rowCount} review items linked to this run{postgresReport ? " from Postgres V2" : ""}</span>
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
        {postgresReport ? <Metric label="Open" value={String(postgresReport.summary.open_review_item_count)} /> : null}
        {postgresReport ? <Metric label="Segment review" value={String(postgresReport.summary.segment_review_count)} /> : null}
        {Object.entries(report.review_queue.by_status ?? {}).map(([status, count]) => (
          <Metric key={status} label={status} value={String(count)} />
        ))}
        {!Object.keys(report.review_queue.by_status ?? {}).length ? <Metric label="Status" value="-" /> : null}
      </div>
      <ReviewItemRows runId={report.run.id} rows={rows} />
    </section>
  );
}

function SegmentsTab({ postgresReport, postgresError }: { postgresReport?: PostgresRunReport; postgresError?: Error | null }) {
  const queryClient = useQueryClient();
  const runKey = String(postgresReport?.run?.run_key ?? "");
  const segmentDecision = useMutation({
    mutationFn: ({ segmentId, decision, notes }: { segmentId: string; decision: "accept" | "reject" | "split"; notes?: string }) =>
      postJson<Record<string, unknown>>(
        `/api/admin/system/postgres-runtime/runs/${encodeURIComponent(runKey)}/segments/${encodeURIComponent(segmentId)}/decision`,
        { decision, notes }
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["postgres-run-report", runKey] });
    }
  });
  if (!postgresReport) {
    return (
      <section className="panel">
        <div className="sectionHeader">
          <h2>Document Segments</h2>
        </div>
        <div className="empty">
          {postgresError ? postgresError.message : "No Postgres segment report is available for this run yet."}
        </div>
      </section>
    );
  }
  return (
    <section className="panel">
      <div className="sectionHeader">
        <div>
          <h2>Document Segments</h2>
          <span>{postgresReport.document_segments.length} logical page-range proposals</span>
        </div>
      </div>
      <div className="metrics compactMetrics">
        <Metric label="Segments" value={String(postgresReport.summary.document_segment_count)} />
        <Metric label="Needs review" value={String(postgresReport.summary.segment_review_count)} />
      </div>
      <div className="reportGrid">
        <Breakdown title="Segment Type" values={postgresReport.summary.segment_type} />
        <Breakdown title="Routes" values={postgresReport.summary.route_status} />
      </div>
      <SegmentRows
        rows={postgresReport.document_segments}
        disabled={!runKey || segmentDecision.isPending}
        onDecision={(segmentId, decision) => segmentDecision.mutate({ segmentId, decision, notes: segmentDecisionNote(decision) })}
      />
    </section>
  );
}

function SegmentRows({
  rows,
  disabled,
  onDecision
}: {
  rows: Array<Record<string, unknown>>;
  disabled: boolean;
  onDecision: (segmentId: string, decision: "accept" | "reject" | "split") => void;
}) {
  if (!rows.length) {
    return <div className="empty">No document segment rows imported for this run.</div>;
  }
  return (
    <div className="tableWrap" tabIndex={0} aria-label="Document segments table">
      <table>
        <thead>
          <tr>
            <th>File</th>
            <th>Pages</th>
            <th>Type</th>
            <th>Confidence</th>
            <th>Review</th>
            <th>Evidence</th>
            <th>Decision</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const segmentId = String(row.segment_id ?? "");
            const review = segmentReview(row);
            return (
              <tr key={String(row.segment_id ?? index)}>
                <td><PathCell title={String(row.relative_path ?? row.source_path ?? "-")} /></td>
                <td>{formatPages(row.page_start, row.page_end)}</td>
                <td>{String(row.segment_type ?? "-")}</td>
                <td>{row.segment_confidence == null ? "-" : String(row.segment_confidence)}</td>
                <td>
                  <div className="cellStack">
                    <span>{row.requires_segment_review ? "required" : "not required"}</span>
                    <span>{review}</span>
                  </div>
                </td>
                <td className="snippetCell">{formatEvidence(row.boundary_evidence)}</td>
                <td>
                  <div className="buttonRow compactButtons">
                    <button className="secondaryButton" disabled={disabled || !segmentId} onClick={() => onDecision(segmentId, "accept")}>Accept</button>
                    <button className="secondaryButton" disabled={disabled || !segmentId} onClick={() => onDecision(segmentId, "split")}>Needs split</button>
                    <button className="secondaryButton dangerText" disabled={disabled || !segmentId} onClick={() => onDecision(segmentId, "reject")}>Reject</button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ReviewItemRows({ runId, rows }: { runId: number | string; rows: Array<Record<string, unknown>> }) {
  return (
    <div className="jsonTableBlock">
      <div className="sectionHeader">
        <h2>Review Items</h2>
        <span>{rows.length} shown</span>
      </div>
      {!rows.length ? <div className="empty">No review items imported for this run.</div> : null}
      {rows.length ? (
        <div className="tableWrap" tabIndex={0} aria-label="Review items table">
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
                      <Link className="viewLink" href={reviewItemHref(row, runId, relativePath)}>
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

function reviewItemHref(row: Record<string, unknown>, runId: number | string, relativePath: string) {
  const id = Number(row.id);
  const params = `run_id=${runId}&status=all`;
  if (Number.isFinite(id) && id > 0) {
    return `/review/${id}?${params}`;
  }
  return `/review?${params}&q=${encodeURIComponent(relativePath)}`;
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
      <pre className="jsonPreview" tabIndex={0} aria-label="Training cycle metrics JSON">{JSON.stringify(metrics, null, 2)}</pre>
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

function LogsTab({ events, postgresBacked }: { events: Array<PipelineRunEvent | Record<string, unknown>>; postgresBacked: boolean }) {
  return (
    <section className="panel">
      <div className="sectionHeader">
        <div>
          <h2>Run Logs</h2>
          <span>{events.length} events{postgresBacked ? " from Postgres V2 graph audit rows" : ""}</span>
        </div>
      </div>
      {postgresBacked ? <PostgresEventTable events={events} /> : <LegacyEventList events={events as PipelineRunEvent[]} />}
    </section>
  );
}

function LegacyEventList({ events }: { events: PipelineRunEvent[] }) {
  if (!events.length) {
    return <div className="empty">No run log rows recorded yet.</div>;
  }
  return (
    <div className="eventList">
      {events.map((event) => (
        <div key={event.id} className={event.level === "error" ? "eventRow errorEvent" : "eventRow"}>
          <span>{event.timestamp}</span>
          <strong>{event.level}{event.payload?.current ? ` ${String(event.payload.current)}/${String(event.payload.total ?? "?")}` : ""}</strong>
          <p>{event.message}</p>
        </div>
      ))}
    </div>
  );
}

function PostgresEventTable({ events }: { events: Array<Record<string, unknown>> }) {
  if (!events.length) {
    return <div className="empty">No graph audit events imported for this run.</div>;
  }
  return (
    <div className="tableWrap" tabIndex={0} aria-label="Postgres graph audit events table">
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Node</th>
            <th>Status</th>
            <th>Duration</th>
            <th>File</th>
            <th>Message</th>
            <th>Warnings / Errors</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event, index) => {
            const payload = event.payload && typeof event.payload === "object" ? (event.payload as Record<string, unknown>) : {};
            return (
              <tr key={String(event.id ?? index)}>
                <td>{String(event.created_at ?? "-")}</td>
                <td>{String(event.node ?? "-")}</td>
                <td>{String(event.status ?? "-")}</td>
                <td>{formatMs(Number(payload.duration_ms ?? 0))}</td>
                <td><PathCell title={String(event.relative_path ?? event.source_path ?? "-")} /></td>
                <td className="snippetCell">{String(event.message ?? "-")}</td>
                <td className="snippetCell">{formatEventProblems(payload)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ArtifactsTab({ report }: { report: RunReport }) {
  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>Artifacts</h2>
      </div>
      <div className="tableWrap" tabIndex={0} aria-label="Run artifacts table">
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
      {rows.length ? <pre className="jsonPreview" tabIndex={0} aria-label={`${title} JSON rows`}>{JSON.stringify(rows.slice(0, 100), null, 2)}</pre> : <div className="empty">No data for this section.</div>}
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

function runExecutionBackend(run: PipelineRun) {
  const metadata = run.run_metadata ?? {};
  const backend = run.execution_backend ?? metadata.execution_backend;
  return typeof backend === "string" && backend ? backend : "subprocess";
}

function postgresExecutionBackend(report: PostgresRunReport) {
  const runBackend = report.run.execution_backend;
  const summaryBackend = report.summary.execution_backend;
  const runtime = report.summary.graph_runtime;
  const runtimeBackend = runtime && typeof runtime === "object" && !Array.isArray(runtime) ? (runtime as Record<string, unknown>).execution_backend : null;
  const backend = runBackend ?? summaryBackend ?? runtimeBackend;
  return typeof backend === "string" && backend ? backend : "-";
}

function formatCost(value: number) {
  return value > 0 ? `$${value.toFixed(4)}` : "$0";
}

function formatPages(start: unknown, end: unknown) {
  if (start == null && end == null) {
    return "-";
  }
  if (start === end || end == null) {
    return `p${String(start)}`;
  }
  return `pp${String(start)}-${String(end)}`;
}

function formatEvidence(value: unknown) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join("; ");
  }
  if (value && typeof value === "object") {
    return JSON.stringify(value);
  }
  return value == null ? "-" : String(value);
}

function segmentReview(row: Record<string, unknown>) {
  const metadata = row.metadata;
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return "-";
  }
  const review = (metadata as Record<string, unknown>).segment_review;
  if (!review || typeof review !== "object" || Array.isArray(review)) {
    return "-";
  }
  const reviewRow = review as Record<string, unknown>;
  return [reviewRow.status, reviewRow.decision].map((value) => String(value ?? "")).filter(Boolean).join(" / ") || "-";
}

function segmentDecisionNote(decision: "accept" | "reject" | "split") {
  return {
    accept: "Segment page range accepted from run report.",
    reject: "Segment page range rejected from run report.",
    split: "Segment page range needs further splitting from run report.",
  }[decision];
}

function formatEventProblems(payload: Record<string, unknown>) {
  const warnings = Array.isArray(payload.warnings) ? payload.warnings : [];
  const errors = Array.isArray(payload.errors) ? payload.errors : [];
  const parts = [...warnings.map((item) => `warning:${String(item)}`), ...errors.map((item) => `error:${String(item)}`)];
  return parts.length ? parts.join("; ") : "-";
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
