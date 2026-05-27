"use client";

import {
  ColumnDef,
  getCoreRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { DataTable } from "../../components/data-table/DataTable";
import { ActiveFilterChips } from "../../components/dashboard/ActiveFilterChips";
import { DashboardSearchToolbar } from "../../components/dashboard/DashboardSearchToolbar";
import { FacetPanel, type FacetDefinition } from "../../components/dashboard/FacetPanel";
import { InspectorPanel } from "../../components/dashboard/InspectorPanel";
import { PathCell } from "../../components/dashboard/PathCell";
import { ProviderConfigBadge } from "../../components/dashboard/ProviderConfigBadge";
import { QualityBadge } from "../../components/dashboard/QualityBadge";
import { ResultTableShell } from "../../components/dashboard/ResultTableShell";
import { RunContextBadge } from "../../components/dashboard/RunContextBadge";
import { EmbeddedPreview } from "../../components/file-preview/EmbeddedPreview";
import { Button } from "../../components/ui/Button";
import { SelectInput, TextArea, TextInput } from "../../components/ui/FormControls";
import { KeyValue } from "../../components/ui/KeyValue";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { MultiTagPicker, TagPicker } from "../../components/ui/TagPicker";
import { fetchJson, postJson, queryString } from "../../lib/api";
import { primaryTagOptions, secondaryTagOptions } from "../../lib/taxonomy";
import type { ReviewFacets, ReviewItem, ReviewSummary } from "../../lib/types";

type Filters = {
  status: string;
  q: string;
  route_status: string;
  review_reason: string;
  primary_tag: string;
  secondary_tag: string;
  content_class: string;
  quality: string;
  placement_status: string;
  warning_type: string;
  source_collection: string;
  run_id: string;
  run_preset_key: string;
  embedding_provider: string;
  llm_tag_provider: string;
  ocr_fallback_provider: string;
  enable_llm_tags: string;
};

const initialFilters: Filters = {
  status: "open",
  q: "",
  route_status: "",
  review_reason: "",
  primary_tag: "",
  secondary_tag: "",
  content_class: "",
  quality: "",
  placement_status: "",
  warning_type: "",
  source_collection: "",
  run_id: "",
  run_preset_key: "",
  embedding_provider: "",
  llm_tag_provider: "",
  ocr_fallback_provider: "",
  enable_llm_tags: ""
};

const filterKeys = Object.keys(initialFilters) as Array<keyof Filters>;

const savedReviewQueues: Array<{ label: string; filters: Partial<Filters> }> = [
  { label: "Open review queue", filters: { status: "open" } },
  { label: "All items for current run", filters: { status: "all" } },
  { label: "OCR poor / empty", filters: { status: "all", warning_type: "ocr_quality_below_threshold" } },
  { label: "Fast run OCR failures", filters: { status: "all", ocr_fallback_provider: "disabled", warning_type: "ocr_quality_below_threshold" } },
  { label: "LLM tag disagreements", filters: { status: "all", review_reason: "llm_tag_disagreement" } },
  { label: "Low confidence tags", filters: { status: "all", review_reason: "tag_confidence_below_threshold" } },
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
  { key: "warning_type", title: "Warnings", facetKey: "warning_type", limit: 8 },
  { key: "placement_status", title: "Placement", facetKey: "placement_status", limit: 8 },
  { key: "source_collection", title: "Collection", facetKey: "source_collection", limit: 8 },
  { key: "embedding_provider", title: "Embedding", facetKey: "embedding_provider", limit: 8 },
  { key: "llm_tag_provider", title: "LLM Provider", facetKey: "llm_tag_provider", limit: 8 },
  { key: "ocr_fallback_provider", title: "OCR Fallback", facetKey: "ocr_fallback_provider", limit: 8 },
  { key: "enable_llm_tags", title: "LLM Tags", facetKey: "llm_tags", valueMap: { enabled: "true", disabled: "false" }, limit: 8 },
  { key: "status", title: "Review Status", facetKey: "review_status", limit: 8 }
];

export default function ReviewPage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<Filters>(initialFilters);
  const [selected, setSelected] = useState<ReviewItem | null>(null);
  const [sorting, setSorting] = useState<SortingState>([]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const next = { ...initialFilters };
    for (const key of Object.keys(initialFilters) as Array<keyof Filters>) {
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

  const reviewPath = `/api/admin/review/items${queryString({ ...filters, limit: 200 })}`;
  const facetsPath = `/api/admin/review/facets${queryString(filters)}`;
  const summary = useQuery({
    queryKey: ["review-summary"],
    queryFn: () => fetchJson<ReviewSummary>("/api/admin/review/summary")
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
  const decision = useMutation({
    mutationFn: (payload: { id: number; body: Record<string, unknown> }) =>
      postJson<ReviewItem>(`/api/admin/review/items/${payload.id}/decision`, payload.body),
    onSuccess: async () => {
      setSelected(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["review-items"] }),
        queryClient.invalidateQueries({ queryKey: ["review-summary"] })
      ]);
    }
  });
  const assignment = useMutation({
    mutationFn: (payload: { id: number; body: Record<string, unknown> }) =>
      postJson<ReviewItem>(`/api/admin/review/items/${payload.id}/assign`, payload.body),
    onSuccess: async (item) => {
      setSelected(item);
      await queryClient.invalidateQueries({ queryKey: ["review-items"] });
    }
  });
  const columns = useMemo<ColumnDef<ReviewItem>[]>(
    () => [
      {
        accessorKey: "relative_path",
        header: "File",
        cell: ({ row }) => (
          <PathCell title={row.original.relative_path} subtitle={row.original.source_path} onClick={() => setSelected(row.original)} />
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
    []
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
        {selected ? (
          <ReviewDrawer
            item={selected}
            saving={decision.isPending}
            assigning={assignment.isPending}
            onClose={() => setSelected(null)}
            onSubmit={(body) => decision.mutate({ id: selected.id, body })}
            onAssign={(body) => assignment.mutate({ id: selected.id, body })}
          />
        ) : (
          <div className="reviewInspector">
            <div className="empty">Select a review item to inspect it.</div>
          </div>
        )}
      </section>
    </main>
  );
}

function ReviewDrawer({
  item,
  saving,
  assigning,
  onClose,
  onSubmit,
  onAssign
}: {
  item: ReviewItem;
  saving: boolean;
  assigning: boolean;
  onClose: () => void;
  onSubmit: (body: Record<string, unknown>) => void;
  onAssign: (body: Record<string, unknown>) => void;
}) {
  const [decision, setDecision] = useState("accept");
  const [correctClass, setCorrectClass] = useState(item.correct_class ?? item.proposed_class ?? "");
  const [correctTag, setCorrectTag] = useState(item.correct_tag ?? item.proposed_tag ?? "");
  const [secondary, setSecondary] = useState(item.correct_secondary_tags?.length ? item.correct_secondary_tags : item.secondary_tags);
  const [destination, setDestination] = useState(item.correct_destination_path ?? item.result.destination_path ?? "");
  const [placementYear, setPlacementYear] = useState(item.correct_placement_year ?? "");
  const [privacy, setPrivacy] = useState(item.correct_privacy ?? item.result.default_privacy ?? "");
  const [reviewStage, setReviewStage] = useState(item.review_stage ?? "");
  const [assignedReviewer, setAssignedReviewer] = useState(item.assigned_reviewer ?? "");
  const [priority, setPriority] = useState(item.priority ?? "");
  const [notes, setNotes] = useState(item.notes ?? "");

  return (
    <InspectorPanel className="reviewInspector" eyebrow="Review Item" title={item.relative_path} onClose={onClose}>
      <div className="drawerGrid">
        <section>
          <h3>File</h3>
          <p className="pathText">{item.source_path}</p>
          <a className="primaryButton" href={`/api/admin/review/items/${item.id}/file`} target="_blank">
            Open File
          </a>
        </section>
        <section>
          <h3>Run Context</h3>
          <KeyValue label="Run" value={item.run_id ? <Link href={`/runs/${item.run_id}/report`}>{item.run_key ?? `Run #${item.run_id}`}</Link> : "-"} />
          <KeyValue label="Preset" value={item.run_preset_key ?? "-"} />
          <KeyValue label="Embedding" value={item.embedding_provider ?? "-"} />
          <KeyValue label="LLM tags" value={item.enable_llm_tags == null ? "-" : item.enable_llm_tags ? "enabled" : "disabled"} />
          <KeyValue label="LLM provider" value={item.llm_tag_provider ?? "-"} />
          <KeyValue label="OCR fallback" value={item.ocr_fallback_provider ?? "-"} />
        </section>
        <section className="wideSection">
          <h3>Preview</h3>
          <EmbeddedPreview previewUrl={`/api/admin/review/items/${item.id}/file`} filename={item.relative_path || item.source_path} />
        </section>
        <section>
          <h3>OCR / Text</h3>
          <div className="textPreview">{item.extraction_text_snippet || "No text snippet available."}</div>
        </section>
        <section>
          <h3>Tagging</h3>
          <KeyValue label="Primary" value={item.proposed_tag ?? "-"} />
          <KeyValue label="Secondary" value={item.secondary_tags.join(", ") || "-"} />
          <KeyValue label="Confidence" value={item.confidence == null ? "-" : item.confidence.toFixed(2)} />
          <ul className="evidenceList">{(item.result.tag_evidence ?? []).map((evidence) => <li key={evidence}>{evidence}</li>)}</ul>
        </section>
        <section>
          <h3>Placement</h3>
          <KeyValue label="Destination" value={item.result.destination_path ?? "-"} />
          <KeyValue label="Status" value={item.result.placement_status ?? "-"} />
          <KeyValue label="Rule" value={item.result.placement_rule ?? "-"} />
          <KeyValue label="Date confidence" value={item.result.placement_date_confidence ?? "-"} />
          <KeyValue label="Privacy" value={item.result.default_privacy ?? "-"} />
        </section>
        <section>
          <h3>Nearest Examples</h3>
          {(item.result.semantic_examples ?? []).length ? (
            <ul className="evidenceList">
              {(item.result.semantic_examples ?? []).map((example, index) => (
                <li key={`${example.relative_path}-${index}`}>
                  {example.correct_primary_tag} {example.score?.toFixed(3)} {example.relative_path}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No semantic examples used.</p>
          )}
        </section>
        <section>
          <h3>Decision</h3>
          <div className="formGrid">
            <SelectInput label="Decision" value={decision} onChange={(event) => setDecision(event.target.value)}>
              <option value="accept">Accept</option>
              <option value="change">Change</option>
              <option value="defer">Defer</option>
              <option value="ignore">Ignore</option>
              <option value="reject">Reject</option>
              <option value="duplicate">Duplicate</option>
            </SelectInput>
            <TextInput label="Correct class" value={correctClass} onChange={(event) => setCorrectClass(event.target.value)} />
            <TagPicker label="Correct primary tag" options={primaryTagOptions} value={correctTag} onChange={setCorrectTag} />
            <MultiTagPicker label="Correct secondary tags" options={secondaryTagOptions} value={secondary} onChange={setSecondary} />
            <TextInput label="Correct destination path" value={destination} onChange={(event) => setDestination(event.target.value)} />
            <TextInput label="Correct placement year/range" value={placementYear} onChange={(event) => setPlacementYear(event.target.value)} />
            <TextInput label="Correct privacy" value={privacy} onChange={(event) => setPrivacy(event.target.value)} />
            <TextInput label="Review stage" value={reviewStage} onChange={(event) => setReviewStage(event.target.value)} />
            <TextInput label="Assigned reviewer" value={assignedReviewer} onChange={(event) => setAssignedReviewer(event.target.value)} />
            <TextInput label="Priority" value={priority} onChange={(event) => setPriority(event.target.value)} />
            <TextArea label="Notes" value={notes} onChange={(event) => setNotes(event.target.value)} rows={4} />
            <Button
              disabled={assigning}
              onClick={() =>
                onAssign({
                  assigned_reviewer: assignedReviewer || null,
                  review_stage: reviewStage || null,
                  priority: priority || null
                })
              }
            >
              {assigning ? "Assigning..." : "Save Assignment"}
            </Button>
            <Button
              variant="primary"
              disabled={saving}
              onClick={() =>
                onSubmit({
                  decision,
                  correct_class: correctClass || null,
                  correct_tag: correctTag || null,
                  correct_secondary_tags: secondary,
                  correct_destination_path: destination || null,
                  correct_placement_year: placementYear || null,
                  correct_privacy: privacy || null,
                  review_stage: reviewStage || null,
                  notes,
                  reviewer: "james",
                  save_as_golden: decision === "accept" || decision === "change"
                })
              }
            >
              {saving ? "Saving..." : "Save Decision"}
            </Button>
          </div>
        </section>
        <section className="wideSection">
          <h3>Raw JSON</h3>
          <pre className="jsonPreview">{JSON.stringify(item.result, null, 2)}</pre>
        </section>
      </div>
    </InspectorPanel>
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
