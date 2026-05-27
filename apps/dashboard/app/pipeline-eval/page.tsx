"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Button } from "../../components/ui/Button";
import { CheckboxField, TextInput } from "../../components/ui/FormControls";
import { KeyValue } from "../../components/ui/KeyValue";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { fetchJson, postJson, queryString } from "../../lib/api";
import type { PipelineEvalComparison, PipelineEvalDrilldown, PipelineEvalRun, PipelineEvalRunResponse } from "../../lib/types";

type DrilldownType = "failures" | "failure_groups" | "results" | "model_usage";

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
  const baselineRun = useMemo(() => {
    if (!activeRun) {
      return null;
    }
    return (evalRuns.data ?? []).find((run) => run.id !== activeRun.id) ?? null;
  }, [activeRun, evalRuns.data]);
  const drilldown = useQuery({
    queryKey: ["pipeline-eval-drilldown", activeRun?.id, drilldownType],
    enabled: Boolean(activeRun),
    queryFn: () =>
      fetchJson<PipelineEvalDrilldown>(
        `/api/admin/pipeline-eval/runs/${activeRun?.id}/results${queryString({ result_type: drilldownType, limit: 200 })}`
      )
  });
  const comparison = useQuery({
    queryKey: ["pipeline-eval-comparison", activeRun?.id, baselineRun?.id],
    enabled: Boolean(activeRun && baselineRun),
    queryFn: () =>
      fetchJson<PipelineEvalComparison>(
        `/api/admin/pipeline-eval/runs/${activeRun?.id}/compare${queryString({ baseline_eval_run_id: baselineRun?.id })}`
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
  const readiness = summary?.production_readiness;
  const metricCards = useMemo(
    () => [
      ["Primary", summary?.primary_accuracy],
      ["Content class", summary?.content_class_accuracy],
      ["OCR quality", summary?.ocr_quality_accuracy],
      ["OCR acceptable", summary?.ocr_acceptable_rate],
      ["OCR fallback", summary?.ocr_fallback_rate],
      ["LLM valid", summary?.llm_structured_output_validity_rate],
      ["Embedding success", summary?.embedding_success_rate],
      ["Semantic top 5", summary?.semantic_same_family_top5_rate],
      ["High-risk min", summary?.high_risk_primary_accuracy_min],
      ["High-conf accuracy", summary?.high_confidence_primary_accuracy],
      ["Evidence coverage", summary?.tag_evidence_presence_rate],
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
                <th>Readiness</th>
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
                  <td>
                    <StatusBadge
                      value={run.summary?.production_readiness?.status ?? "-"}
                      tone={run.summary?.production_readiness?.larger_batch_allowed ? "default" : "danger"}
                    />
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
          {readiness ? (
            <section className="drawerSection wideSection">
              <div className="sectionHeader">
                <div>
                  <h3>Production Readiness</h3>
                  <p className="muted">{readiness.summary}</p>
                </div>
                <StatusBadge value={readiness.status} tone={readiness.larger_batch_allowed ? "default" : "danger"} />
              </div>
              <div className="drawerGrid compactGrid">
                <section>
                  <h4>Decision</h4>
                  <KeyValue label="Larger batch allowed" value={readiness.larger_batch_allowed ? "yes" : "no"} />
                  <KeyValue label="Customer claims allowed" value={readiness.customer_claims_allowed ? "yes" : "no"} />
                  <KeyValue label="Blocking gates" value={readiness.blocking_reasons.join(", ") || "-"} />
                </section>
                <section>
                  <h4>Status Buckets</h4>
                  <KeyValue label="Accepted" value={String(readiness.status_counts.accepted ?? 0)} />
                  <KeyValue label="Review required" value={String(readiness.status_counts.review_required ?? 0)} />
                  <KeyValue label="Failed" value={String(readiness.status_counts.failed ?? 0)} />
                  <KeyValue label="Deferred" value={String(readiness.status_counts.deferred ?? 0)} />
                </section>
                <section>
                  <h4>Reliable Categories</h4>
                  <KeyValue label="Threshold" value={`${readiness.category_min_examples} labels, ${formatPercent(readiness.category_accuracy_threshold)} accuracy`} />
                  <KeyValue label="Reliable" value={formatCategoryList(readiness.reliable_categories)} />
                  <KeyValue label="Unreliable" value={formatCategoryList(readiness.unreliable_categories)} />
                  <KeyValue label="Underrepresented" value={formatCategoryList(readiness.underrepresented_categories)} />
                </section>
                <section>
                  <h4>Required Next Actions</h4>
                  {readiness.required_next_actions.length ? (
                    <ul className="evidenceList">
                      {readiness.required_next_actions.map((action) => (
                        <li key={action}>{action}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="muted">No blocking actions.</p>
                  )}
                </section>
              </div>
            </section>
          ) : null}
          {comparison.data ? (
            <section className="drawerSection wideSection">
              <div className="sectionHeader">
                <div>
                  <h3>Compared With Previous Eval</h3>
                  <p className="muted">{comparison.data.baseline_eval_run.eval_key}</p>
                </div>
                <span>{comparison.data.shared_file_count} shared files</span>
              </div>
              <div className="drawerGrid compactGrid">
                <section>
                  <h4>Outcome Changes</h4>
                  <KeyValue label="Fixed failures" value={String(comparison.data.fixed_failure_count)} />
                  <KeyValue label="Regressed failures" value={String(comparison.data.regressed_failure_count)} />
                  <KeyValue label="Changed tags" value={String(comparison.data.changed_prediction_count)} />
                  <KeyValue label="Changed routes" value={String(comparison.data.changed_review_route_count)} />
                </section>
                <section>
                  <h4>Metric Deltas</h4>
                  {Object.entries(comparison.data.metric_deltas).map(([metric, delta]) => (
                    <KeyValue key={metric} label={metric} value={formatDelta(delta)} />
                  ))}
                </section>
                <section>
                  <h4>Sample Changes</h4>
                  {(comparison.data.changed_predictions.length ? comparison.data.changed_predictions : comparison.data.regressed_failures).slice(0, 5).map((row) => (
                    <p className="pathText" key={String(row.source_path)}>
                      {String(row.relative_path ?? row.source_path)}: {String(row.baseline_predicted_primary_tag ?? "-")} to {String(row.current_predicted_primary_tag ?? "-")}
                    </p>
                  ))}
                  {!comparison.data.changed_predictions.length && !comparison.data.regressed_failures.length ? <p className="muted">No changed predictions or regressions.</p> : null}
                </section>
              </div>
            </section>
          ) : baselineRun ? (
            <section className="drawerSection wideSection">
              <h3>Compared With Previous Eval</h3>
              <p className="muted">{comparison.isError ? `Comparison failed: ${comparison.error.message}` : "Loading comparison..."}</p>
            </section>
          ) : null}
          <div className="drawerGrid">
            <section>
              <h3>Gate</h3>
              {(gate?.checks ?? []).map((check) => (
                <KeyValue key={check.name} label={check.name} value={`${check.status} ${formatPercent(check.value)} ${check.operator} ${formatPercent(check.threshold)}`} />
              ))}
              <KeyValue label="Source mutations" value={String(summary?.source_file_mutations ?? 0)} />
            </section>
            <section>
              <h3>Run Metadata</h3>
              <KeyValue label="Git commit" value={shortCommit(summary?.run_metadata?.git_commit ?? activeRun.run_metadata?.git_commit)} />
              <KeyValue label="Taxonomy" value={String(summary?.run_metadata?.taxonomy_version ?? activeRun.run_metadata?.taxonomy_version ?? "-")} />
              <KeyValue label="Embedding" value={String(summary?.run_metadata?.embedding_provider ?? activeRun.run_metadata?.embedding_provider ?? "-")} />
              <KeyValue label="LLM" value={String(summary?.run_metadata?.llm_provider ?? activeRun.run_metadata?.llm_provider ?? "-")} />
              <KeyValue label="OCR" value={String(summary?.run_metadata?.ocr_mode ?? activeRun.run_metadata?.ocr_mode ?? "-")} />
            </section>
            <section>
              <h3>Golden Set</h3>
              <KeyValue label="Ready" value={summary?.golden_label_readiness?.ready ? "yes" : "no"} />
              <KeyValue label="Label count" value={`${summary?.golden_label_readiness?.total_golden_labels ?? 0}/${summary?.golden_label_readiness?.minimum_label_count ?? 75}`} />
              <KeyValue
                label="Taxonomy coverage"
                value={`${summary?.golden_label_readiness?.covered_primary_count ?? 0}/${summary?.golden_label_readiness?.taxonomy_primary_count ?? 0} (${formatPercent(summary?.golden_label_readiness?.primary_coverage_rate)})`}
              />
              <KeyValue label="Missing primary tags" value={(summary?.golden_label_readiness?.missing_primary_tags ?? []).slice(0, 8).join(", ") || "-"} />
              <KeyValue label="High-risk undercovered" value={(summary?.golden_label_readiness?.underrepresented_high_risk_tags ?? []).join(", ") || "-"} />
            </section>
            <section>
              <h3>Review Routing</h3>
              <KeyValue label="Accuracy" value={formatPercent(summary?.review_routing_accuracy)} />
              <KeyValue label="Precision" value={formatPercent(summary?.review_routing_precision)} />
              <KeyValue label="Recall" value={formatPercent(summary?.review_routing_recall)} />
              <KeyValue label="False accepts" value={String(summary?.review_false_accepts ?? 0)} />
              <KeyValue label="False reviews" value={String(summary?.review_false_reviews ?? 0)} />
              <KeyValue label="High-conf false accepts" value={String(summary?.high_confidence_false_accepts ?? 0)} />
              <KeyValue label="Low-conf false accepts" value={String(summary?.low_confidence_false_accepts ?? 0)} />
              <KeyValue label="Low-conf accepted" value={String(summary?.low_confidence_accepted_count ?? 0)} />
              <KeyValue label="Medium-conf unexplained" value={String(summary?.medium_confidence_unexplained_count ?? 0)} />
              <KeyValue label="Sensitive med/low accepts" value={String(summary?.sensitive_medium_low_confidence_accepts ?? 0)} />
              <KeyValue label="Invalid primary tags" value={String(summary?.invalid_primary_tag_count ?? 0)} />
              <KeyValue label="Unsafe placement proposals" value={String(summary?.unsafe_placement_proposal_count ?? 0)} />
            </section>
            <section>
              <h3>LLM Output</h3>
              <KeyValue label="Structured validity" value={formatPercent(summary?.llm_structured_output_validity_rate)} />
              {Object.entries(summary?.by_llm_status ?? {}).map(([status, count]) => (
                <KeyValue key={status} label={status} value={count} />
              ))}
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
              <KeyValue label="Local calls" value={String((summary?.model_usage?.local_call_count as number | undefined) ?? 0)} />
              <KeyValue label="External calls" value={String((summary?.model_usage?.external_call_count as number | undefined) ?? 0)} />
              <KeyValue label="Unknown cost basis" value={String((summary?.model_usage?.unknown_cost_basis_count as number | undefined) ?? 0)} />
              <KeyValue label="Embedding attempted" value={String((summary?.model_usage?.embedding_attempted_calls as number | undefined) ?? 0)} />
              <KeyValue label="Embedding successful" value={String((summary?.model_usage?.embedding_successful_calls as number | undefined) ?? 0)} />
              <KeyValue label="Placeholder embeddings" value={String((summary?.model_usage?.embedding_placeholder_calls as number | undefined) ?? 0)} />
              <KeyValue label="Failed embeddings" value={String((summary?.model_usage?.embedding_failed_calls as number | undefined) ?? 0)} />
              <KeyValue label="Embedding providers" value={formatMap(summary?.model_usage?.embedding_provider_models)} />
              <KeyValue label="Embedding dimensions" value={formatMap(summary?.model_usage?.embedding_dimensions)} />
              <KeyValue label="Required fields" value={formatPercent(summary?.model_usage?.required_field_completeness_rate as number | null | undefined)} />
              <KeyValue label="Cost basis tracked" value={formatPercent(summary?.model_usage?.cost_basis_completeness_rate as number | null | undefined)} />
              <KeyValue label="Missing fields" value={formatMap(summary?.model_usage?.missing_required_field_counts)} />
              <KeyValue label="Tokens" value={String((summary?.model_usage?.total_tokens as number | undefined) ?? 0)} />
              <KeyValue label="External cost" value={`$${Number((summary?.model_usage?.estimated_external_cost_usd as number | undefined) ?? 0).toFixed(4)}`} />
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
            <section>
              <h3>Confidence Calibration</h3>
              {Object.entries(summary?.confidence_bucket_metrics ?? {}).map(([bucket, metric]) => (
                <KeyValue
                  key={bucket}
                  label={bucket}
                  value={`${formatPercent(metric.primary_accuracy)} primary, ${formatPercent(metric.review_required_rate)} review, ${metric.accepted} accepted, ${metric.false_accepts} false accepts (${metric.primary_correct}/${metric.total})`}
                />
              ))}
            </section>
          </div>
          <div className="buttonRow">
            <Button variant={drilldownType === "failures" ? "primary" : "secondary"} onClick={() => setDrilldownType("failures")}>
              Failures
            </Button>
            <Button variant={drilldownType === "failure_groups" ? "primary" : "secondary"} onClick={() => setDrilldownType("failure_groups")}>
              Failure Groups
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
              <td>{expectedValue(row)}</td>
              <td>{String(row.predicted_primary_tag ?? row.predicted_destination_path ?? row.model ?? "-")}</td>
              <td>{reasonValue(row)}</td>
              <td>{routeValue(row)}</td>
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

function expectedValue(row: Record<string, unknown>) {
  if (typeof row.count === "number" && row.reason) {
    return `${row.count} affected`;
  }
  return String(row.correct_primary_tag ?? row.expected_destination_path ?? row.provider ?? "-");
}

function reasonValue(row: Record<string, unknown>) {
  if (Array.isArray(row.failure_reasons)) {
    return row.failure_reasons.join(", ");
  }
  return String(row.reason ?? row.purpose ?? "-");
}

function routeValue(row: Record<string, unknown>) {
  if (row.affected_route_statuses && typeof row.affected_route_statuses === "object" && !Array.isArray(row.affected_route_statuses)) {
    return formatMap(row.affected_route_statuses);
  }
  return String(row.route_status ?? row.status ?? "-");
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

function formatCategoryList(categories: Array<{ tag: string; total: number; correct: number; accuracy: number | null }>) {
  if (!categories.length) {
    return "-";
  }
  return categories
    .slice(0, 8)
    .map((category) => `${category.tag} ${formatPercent(category.accuracy)} (${category.correct}/${category.total})`)
    .join(", ");
}

function formatDelta(delta: { baseline: number | null; current: number | null; delta: number | null }) {
  const change = delta.delta === null ? "-" : `${delta.delta >= 0 ? "+" : ""}${formatPercent(delta.delta)}`;
  return `${formatPercent(delta.baseline)} to ${formatPercent(delta.current)} (${change})`;
}

function shortCommit(value: unknown) {
  const text = typeof value === "string" ? value : "";
  return text ? text.slice(0, 12) : "-";
}
