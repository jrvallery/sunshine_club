"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "../../components/ui/Button";
import { TextInput } from "../../components/ui/FormControls";
import { KeyValue } from "../../components/ui/KeyValue";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { fetchJson, postJson } from "../../lib/api";
import type { ReviewSummary, SemanticIndexStatus } from "../../lib/types";

type Health = {
  status: string;
};

type LocalInfrastructure = {
  local_only: boolean;
  postgres: Record<string, unknown>;
  qdrant: Record<string, unknown>;
  qdrant_retrieval: Record<string, unknown>;
  docling: Record<string, unknown>;
  parser_providers: Record<string, Record<string, unknown>>;
  parser_policy: Record<string, unknown>;
  cortex: Record<string, unknown>;
  model_call_cache: Record<string, unknown>;
  temporal: Record<string, unknown>;
  observability: Record<string, unknown>;
  provider_registry: {
    validation: { ok: boolean; errors?: string[]; missing_capabilities?: string[] };
    providers: Array<Record<string, unknown>>;
  };
  policy: Record<string, unknown>;
};

type QdrantRebuildResponse = {
  ok: boolean;
  source_row_count: number;
  vector_store: {
    provider: string;
    collection: string | null;
    status: string;
    indexed_count: number;
    skipped_count: number;
    warnings: string[];
  };
};

type PostgresRuntime = {
  ok: boolean;
  summary: {
    pipeline_runs: number;
    pipeline_results: number;
    review_items: number;
    model_usage: number;
    provider_attempts: number;
    document_segments: number;
    pipeline_chunks: number;
    pipeline_chunk_embeddings: number;
  };
  runs: Array<Record<string, unknown>>;
};

type PostgresReviewItems = {
  ok: boolean;
  count: number;
  items: Array<Record<string, unknown>>;
};

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [rebuildRunKey, setRebuildRunKey] = useState("");
  const [rebuildLimit, setRebuildLimit] = useState("");
  const health = useQuery({ queryKey: ["api-health"], queryFn: () => fetchJson<Health>("/api/healthz") });
  const summary = useQuery({ queryKey: ["review-summary"], queryFn: () => fetchJson<ReviewSummary>("/api/admin/review/summary") });
  const semanticIndex = useQuery({ queryKey: ["semantic-index-status"], queryFn: () => fetchJson<SemanticIndexStatus>("/api/admin/semantic-index/status") });
  const infrastructure = useQuery({
    queryKey: ["local-infrastructure"],
    queryFn: () => fetchJson<LocalInfrastructure>("/api/admin/system/local-infrastructure")
  });
  const postgresRuntime = useQuery({
    queryKey: ["postgres-runtime"],
    queryFn: () => fetchJson<PostgresRuntime>("/api/admin/system/postgres-runtime?limit=10"),
    retry: false
  });
  const postgresReviewItems = useQuery({
    queryKey: ["postgres-review-items"],
    queryFn: () => fetchJson<PostgresReviewItems>("/api/admin/system/postgres-runtime/review-items?limit=10"),
    retry: false
  });
  const rebuildQdrant = useMutation({
    mutationFn: () =>
      postJson<QdrantRebuildResponse>("/api/admin/vector-index/qdrant/rebuild", {
        run_key: rebuildRunKey.trim() || undefined,
        limit: Number(rebuildLimit) > 0 ? Number(rebuildLimit) : undefined
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["local-infrastructure"] });
    }
  });
  const providerRows = infrastructure.data?.provider_registry.providers ?? [];

  return (
    <main className="pageShell">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Settings</p>
          <h1>Dashboard Configuration</h1>
        </div>
      </header>
      <section className="panel">
        <h2>Service Status</h2>
        <div className="settingsGrid">
          <KeyValue label="API health" value={health.data?.status ?? "unknown"} />
          <KeyValue label="Review DB" value={summary.data?.db_path ?? "-"} />
          <KeyValue label="Semantic index" value={semanticIndex.data?.index_db ?? "-"} />
          <KeyValue label="Semantic index rows" value={String(semanticIndex.data?.indexed ?? 0)} />
          <KeyValue label="Local only" value={String(infrastructure.data?.local_only ?? "-")} />
          <KeyValue label="Provider registry" value={<StatusBadge value={infrastructure.data?.provider_registry.validation.ok ? "ok" : "needs attention"} tone={infrastructure.data?.provider_registry.validation.ok ? "default" : "danger"} />} />
        </div>
      </section>
      <section className="panel">
        <div className="sectionHeader">
          <h2>Provider Infrastructure</h2>
          <span>{providerRows.length} registered</span>
        </div>
        <div className="settingsGrid">
          <ProviderStatus title="Postgres" status={infrastructure.data?.postgres} />
          <ProviderStatus title="Qdrant" status={infrastructure.data?.qdrant} />
          <ProviderStatus title="Qdrant retrieval" status={infrastructure.data?.qdrant_retrieval} />
          <ProviderStatus title="Docling" status={infrastructure.data?.docling} />
          <ProviderStatus title="Cortex" status={infrastructure.data?.cortex} />
          <ProviderStatus title="Model cache" status={infrastructure.data?.model_call_cache} />
          <ProviderStatus title="Temporal" status={infrastructure.data?.temporal} />
          <ProviderStatus title="Observability" status={infrastructure.data?.observability} />
        </div>
      </section>
      <section className="panel">
        <div className="sectionHeader">
          <h2>Parser Candidate Dependencies</h2>
          <span>{Object.keys(infrastructure.data?.parser_providers ?? {}).length} checked</span>
        </div>
        <div className="settingsGrid">
          <KeyValue label="OCR parser policy" value={String(infrastructure.data?.parser_policy?.ocr_parser_provider ?? "-")} />
          <KeyValue label="Text fallback parser" value={String(infrastructure.data?.parser_policy?.text_parser_provider ?? "-")} />
          <KeyValue label="Hosted providers allowed" value={String(infrastructure.data?.parser_policy?.hosted_allowed ?? false)} />
          <KeyValue label="Allowed parser providers" value={formatList(infrastructure.data?.parser_policy?.allowed)} />
        </div>
        <div className="settingsGrid">
          {Object.entries(infrastructure.data?.parser_providers ?? {}).map(([name, status]) => (
            <ProviderStatus key={name} title={name} status={status} />
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="sectionHeader">
          <h2>Postgres Runtime</h2>
          <StatusBadge value={postgresRuntime.data?.ok ? "connected" : "not connected"} tone={postgresRuntime.data?.ok ? "default" : "danger"} />
        </div>
        <div className="settingsGrid">
          <KeyValue label="Runs" value={String(postgresRuntime.data?.summary.pipeline_runs ?? 0)} />
          <KeyValue label="Results" value={String(postgresRuntime.data?.summary.pipeline_results ?? 0)} />
          <KeyValue label="Review items" value={String(postgresRuntime.data?.summary.review_items ?? 0)} />
          <KeyValue label="Model usage" value={String(postgresRuntime.data?.summary.model_usage ?? 0)} />
          <KeyValue label="Provider attempts" value={String(postgresRuntime.data?.summary.provider_attempts ?? 0)} />
          <KeyValue label="Segments" value={String(postgresRuntime.data?.summary.document_segments ?? 0)} />
          <KeyValue label="Chunks" value={String(postgresRuntime.data?.summary.pipeline_chunks ?? 0)} />
          <KeyValue label="Embeddings" value={String(postgresRuntime.data?.summary.pipeline_chunk_embeddings ?? 0)} />
        </div>
        {postgresRuntime.error ? <p className="dangerText">{String(postgresRuntime.error.message)}</p> : null}
        {postgresRuntime.data?.runs.length ? (
          <div className="tableWrap reportTable">
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Status</th>
                  <th>Results</th>
                  <th>Review</th>
                  <th>Models</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {postgresRuntime.data.runs.map((run) => (
                  <tr key={String(run.id)}>
                    <td>
                      <div className="cellStack">
                        <strong>{String(run.run_key ?? "-")}</strong>
                        <span>{String(run.output_dir ?? "-")}</span>
                      </div>
                    </td>
                    <td>{String(run.status ?? "-")}</td>
                    <td>{String(run.result_count ?? 0)}</td>
                    <td>{String(run.review_required_count ?? 0)}</td>
                    <td>{String(run.model_usage_count ?? 0)}</td>
                    <td>{String(run.updated_at ?? run.created_at ?? "-")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {postgresReviewItems.data?.items.length ? (
          <div className="tableWrap reportTable">
            <table>
              <thead>
                <tr>
                  <th>Review Item</th>
                  <th>Run</th>
                  <th>Status</th>
                  <th>Reason</th>
                  <th>Proposed</th>
                </tr>
              </thead>
              <tbody>
                {postgresReviewItems.data.items.map((item) => (
                  <tr key={String(item.id)}>
                    <td>
                      <div className="cellStack">
                        <strong>{String(item.relative_path ?? item.source_path ?? "-")}</strong>
                        <span>{String(item.source_path ?? "-")}</span>
                      </div>
                    </td>
                    <td>{String(item.run_key ?? "-")}</td>
                    <td>{String(item.status ?? "-")}</td>
                    <td>{String(item.review_reason ?? "-")}</td>
                    <td>{[item.proposed_class, item.proposed_tag].filter(Boolean).join(" / ") || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
      <section className="panel">
        <div className="sectionHeader">
          <h2>Qdrant Collection Rebuild</h2>
          <StatusBadge value={String(infrastructure.data?.qdrant?.provisioned ? "provisioned" : "not provisioned")} tone={infrastructure.data?.qdrant?.provisioned ? "default" : "danger"} />
        </div>
        <div className="formGrid compactForm">
          <TextInput label="Run key" value={rebuildRunKey} onChange={(event) => setRebuildRunKey(event.target.value)} />
          <TextInput label="Limit" value={rebuildLimit} onChange={(event) => setRebuildLimit(event.target.value)} />
          <Button variant="primary" disabled={rebuildQdrant.isPending} onClick={() => rebuildQdrant.mutate()}>
            {rebuildQdrant.isPending ? "Rebuilding..." : "Rebuild Qdrant"}
          </Button>
        </div>
        {rebuildQdrant.data ? (
          <div className="settingsGrid">
            <KeyValue label="Status" value={rebuildQdrant.data.vector_store.status} />
            <KeyValue label="Collection" value={rebuildQdrant.data.vector_store.collection ?? "-"} />
            <KeyValue label="Source rows" value={String(rebuildQdrant.data.source_row_count)} />
            <KeyValue label="Indexed" value={String(rebuildQdrant.data.vector_store.indexed_count)} />
          </div>
        ) : null}
        {rebuildQdrant.error ? <p className="dangerText">{String(rebuildQdrant.error.message)}</p> : null}
      </section>
      <section className="panel">
        <div className="sectionHeader">
          <h2>Provider Registry</h2>
          <span>{infrastructure.data?.provider_registry.validation.ok ? "valid" : "check configuration"}</span>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Capability</th>
                <th>Provider</th>
                <th>Enabled</th>
                <th>Local</th>
                <th>Package</th>
              </tr>
            </thead>
            <tbody>
              {providerRows.map((row) => (
                <tr key={String(row.key)}>
                  <td>{String(row.capability ?? "-")}</td>
                  <td>{String(row.name ?? row.key ?? "-")}</td>
                  <td>{String(row.enabled ?? "-")}</td>
                  <td>{String(row.local_only ?? "-")}</td>
                  <td>{String(row.package ?? "-")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel">
        <h2>Read-Only Safety</h2>
        <p className="muted">Dashboard actions read source files and write review/run artifacts. They do not move, delete, or overwrite source files.</p>
      </section>
    </main>
  );
}

function formatList(value: unknown) {
  return Array.isArray(value) ? value.map(String).join(", ") : "-";
}

function ProviderStatus({ title, status }: { title: string; status?: Record<string, unknown> }) {
  const available = Boolean(status?.available ?? status?.configured ?? status?.provisioned);
  return (
    <div className="breakdown">
      <div className="sectionHeader">
        <h2>{title}</h2>
        <StatusBadge value={available ? "ready" : "check"} tone={available ? "default" : "danger"} />
      </div>
      <KeyValue label="Provider" value={String(status?.provider ?? "-")} />
      <KeyValue label="Local only" value={String(status?.local_only ?? true)} />
      <KeyValue label="URL/path" value={String(status?.url ?? status?.path ?? status?.address ?? "-")} />
      <KeyValue label="Collection/model" value={String(status?.collection ?? status?.model ?? status?.task_queue ?? "-")} />
    </div>
  );
}
