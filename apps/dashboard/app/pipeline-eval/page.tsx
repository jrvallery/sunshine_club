"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Button } from "../../components/ui/Button";
import { CheckboxField, TextInput } from "../../components/ui/FormControls";
import { KeyValue } from "../../components/ui/KeyValue";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { fetchJson, postJson, queryString } from "../../lib/api";
import type { PipelineEvalDrilldown, PipelineEvalRun, PipelineEvalRunResponse } from "../../lib/types";

type DrilldownType = "failures" | "results" | "model_usage";

export default function PipelineEvalPage() {
  const queryClient = useQueryClient();
  const [selectedRun, setSelectedRun] = useState<PipelineEvalRun | null>(null);
  const [drilldownType, setDrilldownType] = useState<DrilldownType>("failures");
  const [outputDir, setOutputDir] = useState(".local/pipeline-eval");
  const [limit, setLimit] = useState("25");
  const [disableSemanticIndex, setDisableSemanticIndex] = useState(false);
  const [enableLlmTags, setEnableLlmTags] = useState(false);
  const [enableOcr, setEnableOcr] = useState(false);

  const evalRuns = useQuery({
    queryKey: ["pipeline-eval-runs"],
    queryFn: () => fetchJson<PipelineEvalRun[]>("/api/admin/pipeline-eval/runs?limit=100")
  });
  const activeRun = selectedRun ?? evalRuns.data?.[0] ?? null;
  const drilldown = useQuery({
    queryKey: ["pipeline-eval-drilldown", activeRun?.id, drilldownType],
    enabled: Boolean(activeRun),
    queryFn: () =>
      fetchJson<PipelineEvalDrilldown>(
        `/api/admin/pipeline-eval/runs/${activeRun?.id}/results${queryString({ result_type: drilldownType, limit: 200 })}`
      )
  });
  const runEval = useMutation({
    mutationFn: () =>
      postJson<PipelineEvalRunResponse>("/api/admin/pipeline-eval/run", {
        output_dir: outputDir,
        limit: Number(limit) > 0 ? Number(limit) : undefined,
        disable_semantic_index: disableSemanticIndex,
        enable_llm_tags: enableLlmTags,
        enable_ocr: enableOcr
      }),
    onSuccess: async (payload) => {
      setSelectedRun(payload.eval_run);
      await queryClient.invalidateQueries({ queryKey: ["pipeline-eval-runs"] });
      await queryClient.invalidateQueries({ queryKey: ["pipeline-eval-drilldown"] });
    }
  });
  const summary = activeRun?.summary;
  const gate = summary?.acceptance_gate;
  const metricCards = useMemo(
    () => [
      ["Primary", summary?.primary_accuracy],
      ["Content class", summary?.content_class_accuracy],
      ["OCR quality", summary?.ocr_quality_accuracy],
      ["Embedding success", summary?.embedding_success_rate],
      ["Semantic top 5", summary?.semantic_same_family_top5_rate],
      ["High-risk min", summary?.high_risk_primary_accuracy_min],
      ["Placement", summary?.placement_destination_accuracy],
      ["Privacy", summary?.privacy_accuracy],
      ["Review route", summary?.review_routing_accuracy]
    ],
    [summary]
  );

  return (
    <main className="pageShell">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Evaluation</p>
          <h1>Pipeline Quality Eval</h1>
        </div>
        <div className="metricStrip">
          <Metric label="Eval runs" value={evalRuns.data?.length ?? 0} />
          <Metric label="Labels" value={summary?.total_golden_labels ?? 0} />
          <Metric label="Failures" value={summary?.failure_count ?? 0} />
        </div>
      </header>

      <section className="panel actionPanel">
        <div>
          <h2>Run Golden-Label Eval</h2>
          <p className="muted">Runs the current LangGraph pipeline against golden labels and writes eval artifacts.</p>
        </div>
        <div className="formGrid compactForm">
          <TextInput label="Output dir" value={outputDir} onChange={(event) => setOutputDir(event.target.value)} />
          <TextInput label="Limit" value={limit} onChange={(event) => setLimit(event.target.value)} />
          <CheckboxField label="Disable semantic index" checked={disableSemanticIndex} onChange={(event) => setDisableSemanticIndex(event.target.checked)} />
          <CheckboxField label="Enable LLM tags" checked={enableLlmTags} onChange={(event) => setEnableLlmTags(event.target.checked)} />
          <CheckboxField label="Enable OCR" checked={enableOcr} onChange={(event) => setEnableOcr(event.target.checked)} />
          <Button variant="primary" disabled={runEval.isPending} onClick={() => runEval.mutate()}>
            {runEval.isPending ? "Running..." : "Run Eval"}
          </Button>
        </div>
      </section>

      <section className="bands">
        {metricCards.map(([label, value]) => (
          <div className="breakdown" key={String(label)}>
            <h2>{label}</h2>
            <div className="metricValue">{formatPercent(value as number | null | undefined)}</div>
          </div>
        ))}
      </section>

      <section className="panel">
        <div className="sectionHeader">
          <h2>Eval History</h2>
          <span>{evalRuns.data?.length ?? 0} shown</span>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Eval</th>
                <th>Gate</th>
                <th>Labels</th>
                <th>Primary</th>
                <th>Embeddings</th>
                <th>Semantic</th>
                <th>Placement</th>
                <th>Failures</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {(evalRuns.data ?? []).map((run) => (
                <tr key={run.id}>
                  <td>
                    <button className="linkButton fileCell" onClick={() => setSelectedRun(run)}>
                      <strong>{run.eval_key}</strong>
                      <span>{run.output_dir}</span>
                    </button>
                  </td>
                  <td>
                    <StatusBadge value={run.summary?.acceptance_gate?.status ?? run.status} tone={run.summary?.acceptance_gate?.status === "fail" ? "danger" : "default"} />
                  </td>
                  <td>{run.total_golden_labels ?? "-"}</td>
                  <td>{formatPercent(run.primary_accuracy)}</td>
                  <td>{formatPercent(run.summary?.embedding_success_rate)}</td>
                  <td>{formatPercent(run.summary?.semantic_same_family_top5_rate)}</td>
                  <td>{formatPercent(run.summary?.placement_destination_accuracy)}</td>
                  <td>{run.failure_count ?? "-"}</td>
                  <td>{run.updated_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {activeRun ? (
        <section className="panel">
          <div className="sectionHeader">
            <div>
              <h2>{activeRun.eval_key}</h2>
              <p className="muted">{activeRun.output_dir}</p>
            </div>
            <StatusBadge value={gate?.status ?? activeRun.status} tone={gate?.status === "fail" ? "danger" : "default"} />
          </div>
          <div className="drawerGrid">
            <section>
              <h3>Gate</h3>
              {(gate?.checks ?? []).map((check) => (
                <KeyValue key={check.name} label={check.name} value={`${check.status} ${formatPercent(check.value)} ${check.operator} ${formatPercent(check.threshold)}`} />
              ))}
              <KeyValue label="Source mutations" value={String(summary?.source_file_mutations ?? 0)} />
            </section>
            <section>
              <h3>Failure Reasons</h3>
              {Object.entries(summary?.by_failure_reason ?? {}).map(([reason, count]) => (
                <KeyValue key={reason} label={reason} value={count} />
              ))}
            </section>
            <section>
              <h3>Model Usage</h3>
              <KeyValue label="Rows" value={String((summary?.model_usage?.total_model_usage_rows as number | undefined) ?? 0)} />
              <KeyValue label="External calls" value={String((summary?.model_usage?.external_call_count as number | undefined) ?? 0)} />
              <KeyValue label="Embedding attempted" value={String((summary?.model_usage?.embedding_attempted_calls as number | undefined) ?? 0)} />
              <KeyValue label="Embedding successful" value={String((summary?.model_usage?.embedding_successful_calls as number | undefined) ?? 0)} />
              <KeyValue label="Placeholder embeddings" value={String((summary?.model_usage?.embedding_placeholder_calls as number | undefined) ?? 0)} />
              <KeyValue label="Failed embeddings" value={String((summary?.model_usage?.embedding_failed_calls as number | undefined) ?? 0)} />
              <KeyValue label="Embedding providers" value={formatMap(summary?.model_usage?.embedding_provider_models)} />
              <KeyValue label="Embedding dimensions" value={formatMap(summary?.model_usage?.embedding_dimensions)} />
              <KeyValue label="Runtime ms" value={String((summary?.model_usage?.total_runtime_ms as number | undefined) ?? 0)} />
            </section>
            <section>
              <h3>Retrieval</h3>
              <KeyValue label="Same-family top 5" value={formatPercent(summary?.semantic_same_family_top5_rate)} />
              <KeyValue label="Embedding success" value={formatPercent(summary?.embedding_success_rate)} />
            </section>
            <section>
              <h3>Category Reliability</h3>
              <KeyValue label="High-risk min" value={formatPercent(summary?.high_risk_primary_accuracy_min)} />
              {Object.entries(summary?.high_risk_primary_tag_metrics ?? {}).map(([tag, metric]) => (
                <KeyValue key={tag} label={tag} value={`${formatPercent(metric.accuracy)} (${metric.correct}/${metric.total})`} />
              ))}
            </section>
          </div>
          <div className="buttonRow">
            <Button variant={drilldownType === "failures" ? "primary" : "secondary"} onClick={() => setDrilldownType("failures")}>
              Failures
            </Button>
            <Button variant={drilldownType === "results" ? "primary" : "secondary"} onClick={() => setDrilldownType("results")}>
              Results
            </Button>
            <Button variant={drilldownType === "model_usage" ? "primary" : "secondary"} onClick={() => setDrilldownType("model_usage")}>
              Model Usage
            </Button>
          </div>
          <EvalRows rows={drilldown.data?.items ?? []} />
        </section>
      ) : null}
    </main>
  );
}

function EvalRows({ rows }: { rows: Array<Record<string, unknown>> }) {
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th>File</th>
            <th>Expected</th>
            <th>Predicted</th>
            <th>Reason</th>
            <th>Route</th>
            <th>Semantic</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.source_path ?? index}`}>
              <td className="pathText">{String(row.relative_path ?? row.source_path ?? "-")}</td>
              <td>{String(row.correct_primary_tag ?? row.expected_destination_path ?? row.provider ?? "-")}</td>
              <td>{String(row.predicted_primary_tag ?? row.predicted_destination_path ?? row.model ?? "-")}</td>
              <td>{Array.isArray(row.failure_reasons) ? row.failure_reasons.join(", ") : String(row.reason ?? row.purpose ?? "-")}</td>
              <td>{String(row.route_status ?? row.status ?? "-")}</td>
              <td>
                <div className="cellStack">
                  <strong>{String(row.semantic_retrieval_quality ?? "-")}</strong>
                  <span>{semanticDetail(row)}</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
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

function semanticDetail(row: Record<string, unknown>) {
  const count = row.semantic_same_family_top5_count;
  const top = row.semantic_top1_primary_tag;
  if (count === undefined && top === undefined) {
    return "-";
  }
  return `same-family top5: ${String(count ?? 0)}; top1: ${String(top ?? "-")}`;
}

function formatMap(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return "-";
  }
  const entries = Object.entries(value as Record<string, unknown>);
  if (!entries.length) {
    return "-";
  }
  return entries.map(([key, count]) => `${key} (${String(count)})`).join(", ");
}
