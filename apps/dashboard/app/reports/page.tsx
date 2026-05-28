"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { PathCell } from "../../components/dashboard/PathCell";
import { Button } from "../../components/ui/Button";
import { TextInput } from "../../components/ui/FormControls";
import { KeyValue } from "../../components/ui/KeyValue";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { postJson } from "../../lib/api";
import type { SemanticSearchResponse } from "../../lib/types";

export default function ReportsPage() {
  const [query, setQuery] = useState("");
  const [collection, setCollection] = useState("");
  const [runKey, setRunKey] = useState("");
  const [primaryTag, setPrimaryTag] = useState("");
  const [contentClass, setContentClass] = useState("");
  const [limit, setLimit] = useState("10");
  const search = useMutation({
    mutationFn: () =>
      postJson<SemanticSearchResponse>("/api/admin/search/semantic", {
        query,
        collection: collection.trim() || undefined,
        run_key: runKey.trim() || undefined,
        primary_tag: primaryTag.trim() || undefined,
        content_class: contentClass.trim() || undefined,
        limit: Number(limit) > 0 ? Number(limit) : 10
      })
  });
  const data = search.data;
  return (
    <main className="pageShell">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Local Search</p>
          <h1>Verified Content Search</h1>
          <p className="muted">Citation-first semantic search over the local Qdrant index. No hosted APIs are used by this request.</p>
        </div>
      </header>

      <section className="panel">
        <div className="sectionHeader">
          <div>
            <h2>Query</h2>
            <span>Search indexed chunks with optional metadata filters.</span>
          </div>
          <Button disabled={!query.trim() || search.isPending} onClick={() => search.mutate()}>
            {search.isPending ? "Searching..." : "Search"}
          </Button>
        </div>
        <div className="formGrid">
          <TextInput label="Search text" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="historical club summary founders dental care" />
          <TextInput label="Collection" value={collection} onChange={(event) => setCollection(event.target.value)} placeholder="sunshine_chunks" />
          <TextInput label="Run key" value={runKey} onChange={(event) => setRunKey(event.target.value)} placeholder="optional run filter" />
          <TextInput label="Primary tag" value={primaryTag} onChange={(event) => setPrimaryTag(event.target.value)} placeholder="optional tag filter" />
          <TextInput label="Content class" value={contentClass} onChange={(event) => setContentClass(event.target.value)} placeholder="optional class filter" />
          <TextInput label="Limit" value={limit} onChange={(event) => setLimit(event.target.value)} />
        </div>
        {search.isError ? <div className="empty dangerText">Search failed: {search.error.message}</div> : null}
      </section>

      {data ? (
        <section className="panel">
          <div className="sectionHeader">
            <div>
              <h2>Results</h2>
              <span>{data.matches.length} citation rows from {data.collection ?? data.provider}</span>
            </div>
            <StatusBadge value={data.status} tone={data.ok ? "default" : "danger"} />
          </div>
          <div className="runMetaGrid">
            <KeyValue label="Provider" value={data.provider} />
            <KeyValue label="Collection" value={String(data.collection ?? "-")} />
            <KeyValue label="Local only" value={String(data.local_only)} />
            <KeyValue label="Warnings" value={data.warnings.length ? data.warnings.join(", ") : "-"} />
          </div>
          <div className="tableWrap" tabIndex={0} aria-label="Semantic search result table">
            <table>
              <thead>
                <tr>
                  <th>Score</th>
                  <th>File</th>
                  <th>Chunk</th>
                  <th>Pages</th>
                  <th>Snippet</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {data.matches.map((match, index) => (
                  <tr key={`${match.chunk_id ?? index}`}>
                    <td>{match.score == null ? "-" : Number(match.score).toFixed(4)}</td>
                    <td><PathCell title={String(match.relative_path ?? match.source_path ?? "-")} /></td>
                    <td>{String(match.chunk_id ?? match.chunk_index ?? "-")}</td>
                    <td>{formatPages(match.page_start, match.page_end)}</td>
                    <td className="snippetCell">{String(match.text_snippet ?? "-")}</td>
                    <td className="snippetCell">{String(match.retrieval_explanation ?? "-")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </main>
  );
}

function formatPages(start?: number | null, end?: number | null) {
  if (start == null && end == null) {
    return "-";
  }
  if (start != null && end != null && start !== end) {
    return `${start}-${end}`;
  }
  return String(start ?? end);
}
