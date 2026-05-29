"use client";

import {
  ColumnDef,
  getCoreRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable
} from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { DataTable } from "../../components/data-table/DataTable";
import { ActiveFilterChips } from "../../components/dashboard/ActiveFilterChips";
import { DashboardSearchToolbar } from "../../components/dashboard/DashboardSearchToolbar";
import { FacetPanel, type FacetDefinition } from "../../components/dashboard/FacetPanel";
import { PathCell } from "../../components/dashboard/PathCell";
import { ProviderConfigBadge } from "../../components/dashboard/ProviderConfigBadge";
import { QualityBadge } from "../../components/dashboard/QualityBadge";
import { ResultTableShell } from "../../components/dashboard/ResultTableShell";
import { RunContextBadge } from "../../components/dashboard/RunContextBadge";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { TagPicker } from "../../components/ui/TagPicker";
import { fetchJson, queryString } from "../../lib/api";
import { primaryTagOptions, secondaryTagOptions } from "../../lib/taxonomy";
import type { ReviewFacets, ReviewItem, ReviewSummary } from "../../lib/types";

type Filters = {
  source: "postgres";
  status: string;
  q: string;
  route_status: string;
  review_reason: string;
  primary_tag: string;
  secondary_tag: string;
  content_class: string;
  quality: string;
  placement_status: string;
  confidence_bucket: string;
  warning_type: string;
  source_collection: string;
  run_id: string;
  run_preset_key: string;
  embedding_provider: string;
  llm_tag_provider: string;
  ocr_fallback_provider: string;
  ocr_fallback_used: string;
  enable_llm_tags: string;
};

const initialFilters: Filters = {
  source: "postgres",
  status: "open",
  q: "",
  route_status: "",
  review_reason: "",
  primary_tag: "",
  secondary_tag: "",
  content_class: "",
  quality: "",
  placement_status: "",
  confidence_bucket: "",
  warning_type: "",
  source_collection: "",
  run_id: "",
  run_preset_key: "",
  embedding_provider: "",
  llm_tag_provider: "",
  ocr_fallback_provider: "",
  ocr_fallback_used: "",
  enable_llm_tags: ""
};

const filterKeys = Object.keys(initialFilters) as Array<keyof Filters>;

const savedReviewQueues: Array<{ label: string; filters: Partial<Filters> }> = [
  { label: "Open review queue", filters: { status: "open" } },
  { label: "All items for current run", filters: { status: "all" } },
  { label: "OCR poor / empty", filters: { status: "all", warning_type: "ocr_quality_below_threshold" } },
  { label: "OCR fallback used", filters: { status: "all", ocr_fallback_used: "used" } },
  { label: "Fast run OCR failures", filters: { status: "all", ocr_fallback_provider: "disabled", warning_type: "ocr_quality_below_threshold" } },
  { label: "LLM tag disagreements", filters: { status: "all", review_reason: "llm_tag_disagreement" } },
  { label: "Low confidence tags", filters: { status: "all", review_reason: "tag_confidence_below_threshold" } },
  { label: "Low confidence bucket", filters: { status: "all", confidence_bucket: "low" } },
  { label: "Segment boundary review", filters: { status: "all", route_status: "review_segment_boundary" } },
  { label: "Placement / date review", filters: { status: "all", placement_status: "needs_review" } },
  { label: "Privacy-sensitive", filters: { status: "all", warning_type: "privacy" } },
  { label: "Route candidate audit sample", filters: { status: "all", review_reason: "qa_random_route_candidate_sample" } },
  { label: "Technical defer", filters: { status: "all", review_reason: "defer_technical" } },
  { label: "Failed extraction", filters: { status: "all", route_status: "review_failed_extraction" } }
];

const reviewFacetDefinitions: Array<FacetDefinition<keyof Filters & string>> = [
  { key: "run_id", title: "Run", facetKey: "run", limit: 8 },
  { key: "run_preset_key", title: "Preset", facetKey: "preset", limit: 8 },
  { key: "review_reason", title: "Reason", facetKey: "review_reason", limit: 8 },
  { key: "route_status", title: "Route", facetKey: "route_status", limit: 8 },
  { key: "primary_tag", title: "Primary Tag", facetKey: "primary_tag", limit: 8 },
  { key: "content_class", title: "Class", facetKey: "content_class", limit: 8 },
  { key: "quality", title: "Quality", facetKey: "quality", limit: 8 },
  { key: "confidence_bucket", title: "Confidence", facetKey: "confidence_bucket", limit: 8 },
  { key: "warning_type", title: "Warnings", facetKey: "warning_type", limit: 8 },
  { key: "placement_status", title: "Placement", facetKey: "placement_status", limit: 8 },
  { key: "source_collection", title: "Collection", facetKey: "source_collection", limit: 8 },
  { key: "embedding_provider", title: "Embedding", facetKey: "embedding_provider", limit: 8 },
  { key: "llm_tag_provider", title: "LLM Provider", facetKey: "llm_tag_provider", limit: 8 },
  { key: "ocr_fallback_provider", title: "OCR Fallback", facetKey: "ocr_fallback_provider", limit: 8 },
  { key: "ocr_fallback_used", title: "Fallback Used", facetKey: "ocr_fallback_used", limit: 8 },
  { key: "enable_llm_tags", title: "LLM Tags", facetKey: "llm_tags", valueMap: { enabled: "true", disabled: "false" }, limit: 8 },
  { key: "status", title: "Review Status", facetKey: "review_status", limit: 8 }
];

export default function ReviewPage() {
  const router = useRouter();
  const [filters, setFilters] = useState<Filters>(initialFilters);
  const [sorting, setSorting] = useState<SortingState>([]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const next = { ...initialFilters };
    for (const key of Object.keys(initialFilters) as Array<keyof Filters>) {
      if (key === "source") {
        continue;
      }
      const value = params.get(key);
      if (value !== null) {
        next[key] = value;
      }
    }
    setFilters(next);
  }, []);
  function updateFilters(patch: Partial<Filters>) {
    const next = { ...filters, ...patch };
    setFilters(next);
    const params = new URLSearchParams();
    for (const key of filterKeys) {
      const value = next[key];
      if (value && value !== initialFilters[key]) {
        params.set(key, value);
      }
    }
    window.history.replaceState(null, "", `${window.location.pathname}${params.toString() ? `?${params.toString()}` : ""}`);
  }

  function clearFilters() {
    updateFilters(initialFilters);
  }

  function reviewDetailHref(itemId: number | string) {
    const params = new URLSearchParams();
    for (const key of filterKeys) {
      const value = filters[key];
      if (value && value !== initialFilters[key]) {
        params.set(key, value);
      }
    }
    return `/review/${itemId}${params.toString() ? `?${params.toString()}` : ""}`;
  }

  const reviewPath = `/api/admin/review/items${queryString({ ...filters, limit: 200 })}`;
  const facetsPath = `/api/admin/review/facets${queryString(filters)}`;
  const summary = useQuery({
    queryKey: ["review-summary", filters.source],
    queryFn: () => fetchJson<ReviewSummary>(`/api/admin/review/summary${queryString({ source: filters.source })}`)
  });
  const items = useQuery({
    queryKey: ["review-items", filters],
    queryFn: () => fetchJson<ReviewItem[]>(reviewPath)
  });
  const facets = useQuery({
    queryKey: ["review-facets", filters],
    queryFn: () => fetchJson<ReviewFacets>(facetsPath),
    placeholderData: (previousData) => previousData ?? {}
  });
  const columns = useMemo<ColumnDef<ReviewItem>[]>(
    () => [
      {
        accessorKey: "relative_path",
        header: "File",
        cell: ({ row }) => (
          <PathCell
            title={row.original.relative_path}
            subtitle={row.original.source_path}
            onClick={() => router.push(reviewDetailHref(row.original.id))}
          />
        )
      },
      {
        id: "run",
        header: "Run",
        cell: ({ row }) => <RunLink item={row.original} />
      },
      {
        id: "run_config",
        header: "Run Config",
        cell: ({ row }) => <RunConfig item={row.original} />
      },
      {
        id: "segment",
        header: "Segment",
        cell: ({ row }) => <SegmentCell item={row.original} />
      },
      {
        id: "model_usage",
        header: "Models",
        cell: ({ row }) => <ModelUsageCell item={row.original} />
      },
      { accessorKey: "review_reason", header: "Reason" },
      { accessorKey: "proposed_class", header: "Class" },
      { accessorKey: "proposed_tag", header: "Primary Tag" },
      {
        id: "secondary_tags",
        header: "Secondary",
        cell: ({ row }) => row.original.secondary_tags.join(", ") || "-"
      },
      {
        id: "destination",
        header: "Destination",
        cell: ({ row }) => row.original.result.destination_path ?? "-"
      },
      {
        id: "placement",
        header: "Placement",
        cell: ({ row }) => (
          <StatusBadge value={row.original.result.placement_status ?? "-"} tone={row.original.result.placement_status === "needs_review" ? "danger" : "default"} />
        )
      },
      {
        accessorKey: "confidence",
        header: "Confidence",
        cell: ({ row }) => (row.original.confidence == null ? "-" : row.original.confidence.toFixed(2))
      },
      {
        id: "quality",
        header: "Quality",
        cell: ({ row }) => <QualityBadge value={row.original.result.quality} />
      },
      {
        id: "warnings",
        header: "Warnings",
        cell: ({ row }) => (row.original.display_warnings ?? row.original.warnings).length
      },
      { accessorKey: "status", header: "Review Status" },
      { accessorKey: "updated_at", header: "Updated" }
    ],
    [filters] // eslint-disable-line react-hooks/exhaustive-deps
  );
  const table = useReactTable({
    data: items.data ?? [],
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel()
  });

  return (
    <main className="pageShell">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Review</p>
          <h1>Pipeline Review Queue</h1>
          {filters.run_id ? (
            <p className="muted">
              Showing review items from run <Link href={`/runs/${filters.run_id}/report`}>#{filters.run_id}</Link>
            </p>
          ) : null}
        </div>
        <div className="metricStrip">
          <Metric label="Open" value={summary.data?.review_by_status.open ?? 0} />
          <Metric label="Resolved" value={summary.data?.review_by_status.resolved ?? 0} />
          <Metric label="Golden" value={summary.data?.total_golden_labels ?? 0} />
        </div>
      </header>

      <DashboardSearchToolbar searchPlaceholder="Search path or OCR snippet" searchValue={filters.q} onSearchChange={(value) => updateFilters({ q: value })}>
        <span className="pill">Postgres</span>
        <select
          aria-label="Saved review queues"
          value=""
          onChange={(event) => {
            const queue = savedReviewQueues.find((item) => item.label === event.target.value);
            if (queue) {
                updateFilters({ ...initialFilters, ...queue.filters, run_id: filters.run_id });
            }
          }}
        >
          <option value="">Saved review queues</option>
          {savedReviewQueues.map((queue) => (
            <option key={queue.label} value={queue.label}>{queue.label}</option>
          ))}
        </select>
        <div className="segmentedControl">
          {["open", "resolved", "all"].map((status) => (
            <button className={filters.status === status ? "active" : ""} key={status} onClick={() => updateFilters({ status })}>
              {status}
            </button>
          ))}
        </div>
        <TagPicker label="Primary tag" options={primaryTagOptions} value={filters.primary_tag} onChange={(value) => updateFilters({ primary_tag: value })} />
        <TagPicker label="Secondary tag" options={secondaryTagOptions} value={filters.secondary_tag} onChange={(value) => updateFilters({ secondary_tag: value })} />
        <button className="secondaryButton" onClick={clearFilters}>Clear Filters</button>
      </DashboardSearchToolbar>

      <ActiveFilterChips filters={filters} defaults={initialFilters} onRemove={(key) => updateFilters({ [key]: initialFilters[key] } as Partial<Filters>)} />

      <section className="reviewWorkspace">
        <FacetPanel
          className="reviewFacetPanel"
          definitions={reviewFacetDefinitions}
          facets={facets.data ?? {}}
          filters={filters}
          onToggle={(key, value) => updateFilters({ [key]: filters[key] === value ? "" : value } as Partial<Filters>)}
        />
        <ResultTableShell>
          <DataTable table={table} loading={items.isLoading} emptyText="No review items match these filters." />
        </ResultTableShell>
      </section>
    </main>
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

function RunLink({ item }: { item: ReviewItem }) {
  return <RunContextBadge runId={item.run_id} runKey={item.run_key} preset={item.run_preset_key} />;
}

function RunConfig({ item }: { item: ReviewItem }) {
  if (!item.run_id) {
    return <span className="muted">-</span>;
  }
  return (
    <ProviderConfigBadge
      embeddingProvider={item.embedding_provider}
      llmEnabled={item.enable_llm_tags}
      llmProvider={item.llm_tag_provider}
      ocrProvider={item.ocr_fallback_provider}
    />
  );
}

function ModelUsageCell({ item }: { item: ReviewItem }) {
  const usage = item.model_usage_summary;
  if (!usage?.total_calls) {
    return <span className="muted">-</span>;
  }
  return (
    <div className="cellStack">
      <strong>{usage.total_calls} calls</strong>
      <span>{usage.external_calls} external / {usage.local_calls} local</span>
      <span>{usage.scope === "file" ? "file scoped" : "run scoped"}</span>
    </div>
  );
}

function SegmentCell({ item }: { item: ReviewItem }) {
  const segmentId = item.segment_id ?? item.result.segment_id;
  if (!segmentId) {
    return <span className="muted">-</span>;
  }
  const pageRange = formatPages(item.page_start ?? item.result.page_start, item.page_end ?? item.result.page_end);
  const evidence = item.segment_boundary_evidence ?? item.result.segment_boundary_evidence ?? [];
  return (
    <div className="cellStack">
      <strong>{pageRange}</strong>
      <span>{item.segment_type ?? item.result.segment_type ?? "segment"}</span>
      <span>{item.segment_title ?? item.result.segment_title ?? segmentId}</span>
      {evidence.length ? <span>{evidence.slice(0, 2).join(" | ")}</span> : null}
    </div>
  );
}

function formatPages(start?: number | null, end?: number | null) {
  if (start == null && end == null) {
    return "pages -";
  }
  if (start != null && end != null && start !== end) {
    return `pp. ${start}-${end}`;
  }
  return `p. ${start ?? end}`;
}
