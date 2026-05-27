"use client";

import { useQuery } from "@tanstack/react-query";

import { KeyValue } from "../../components/ui/KeyValue";
import { fetchJson } from "../../lib/api";
import type { ReviewSummary, SemanticIndexStatus } from "../../lib/types";

type Health = {
  status: string;
};

export default function SettingsPage() {
  const health = useQuery({ queryKey: ["api-health"], queryFn: () => fetchJson<Health>("/api/healthz") });
  const summary = useQuery({ queryKey: ["review-summary"], queryFn: () => fetchJson<ReviewSummary>("/api/admin/review/summary") });
  const semanticIndex = useQuery({ queryKey: ["semantic-index-status"], queryFn: () => fetchJson<SemanticIndexStatus>("/api/admin/semantic-index/status") });

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
        </div>
      </section>
      <section className="panel">
        <h2>Read-Only Safety</h2>
        <p className="muted">Dashboard actions read source files and write review/run artifacts. They do not move, delete, or overwrite source files.</p>
      </section>
    </main>
  );
}
