"use client";

import { ColumnDef, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { VirtualDataTable } from "../../components/data-table/VirtualDataTable";
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
import { KeyValue } from "../../components/ui/KeyValue";
import { fetchJson, postJson, queryString } from "../../lib/api";
import { useDebouncedValue } from "../../lib/hooks";
import type { FileFacets, FileInspection, FileSearchItem, FileSearchResponse, PipelineRun, ReviewItem } from "../../lib/types";

type FileFilters = {
  q: string;
  extension: string;
  source_collection: string;
  content_class: string;
  primary_tag: string;
  secondary_tag: string;
  route_status: string;
  review_status: string;
  ocr_quality: string;
  warning_type: string;
  placement_status: string;
  run_id: string;
  sort: string;
};

const filterKeys = [
  "q",
  "extension",
  "source_collection",
  "content_class",
  "primary_tag",
  "secondary_tag",
  "route_status",
  "review_status",
  "ocr_quality",
  "warning_type",
  "placement_status",
  "run_id",
  "sort"
] as const;

const savedSearches: Array<{ label: string; filters: Partial<FileFilters> }> = [
  { label: "OCR poor or empty", filters: { ocr_quality: "poor" } },
  { label: "Route candidates", filters: { route_status: "route_candidate" } },
  { label: "Meeting records", filters: { primary_tag: "meeting_records" } },
  { label: "Annual tea", filters: { primary_tag: "annual_spring_tea" } },
  { label: "Failed extraction", filters: { route_status: "review_failed_extraction" } },
  { label: "Missing placement date", filters: { placement_status: "missing_date" } }
];

const defaultFilters: FileFilters = {
  q: "",
  extension: "",
  source_collection: "",
  content_class: "",
  primary_tag: "",
  secondary_tag: "",
  route_status: "",
  review_status: "",
  ocr_quality: "",
  warning_type: "",
  placement_status: "",
  run_id: "",
  sort: "updated_desc"
};

const fileFacetDefinitions: Array<FacetDefinition<keyof FileFilters & string>> = [
  { key: "extension", title: "Extension", facetKey: "extension" },
  { key: "source_collection", title: "Collection", facetKey: "source_collection" },
  { key: "content_class", title: "Class", facetKey: "content_class" },
  { key: "primary_tag", title: "Primary Tag", facetKey: "primary_tag" },
  { key: "secondary_tag", title: "Secondary Tag", facetKey: "secondary_tag" },
  { key: "route_status", title: "Route", facetKey: "route_status" },
  { key: "review_status", title: "Review", facetKey: "review_status" },
  { key: "ocr_quality", title: "OCR Quality", facetKey: "ocr_quality" },
  { key: "warning_type", title: "Warnings", facetKey: "warning_type" },
  { key: "placement_status", title: "Placement", facetKey: "placement_status" },
  { key: "run_id", title: "Latest Run", facetKey: "latest_run" }
];

export default function FilesPage() {
  return (
    <Suspense fallback={<main className="pageShell"><div className="empty">Loading file explorer...</div></main>}>
      <FilesPageContent />
    </Suspense>
  );
}

function FilesPageContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const filters = useMemo(() => filtersFromParams(searchParams), [searchParams]);
  const [queryText, setQueryText] = useState(filters.q);
  const [customSavedSearches, setCustomSavedSearches] = useState<Array<{ label: string; filters: Partial<FileFilters> }>>([]);
  const debouncedQuery = useDebouncedValue(queryText, 300);
  const selectedId = numberParam(searchParams.get("file_id"));
  const allSavedSearches = useMemo(() => [...savedSearches, ...customSavedSearches], [customSavedSearches]);

  useEffect(() => {
    setQueryText(filters.q);
  }, [filters.q]);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem("sunshine-file-saved-searches");
      if (stored) {
        setCustomSavedSearches(JSON.parse(stored));
      }
    } catch {
      setCustomSavedSearches([]);
    }
  }, []);

  useEffect(() => {
    if (debouncedQuery !== filters.q) {
      updateFilters({ q: debouncedQuery });
    }
  }, [debouncedQuery]); // eslint-disable-line react-hooks/exhaustive-deps

  const search = useQuery({
    queryKey: ["file-search", filters],
    queryFn: () => fetchJson<FileSearchResponse>(`/api/admin/files/search${queryString(apiParams(filters, { limit: 300 }))}`),
    placeholderData: (previousData) => previousData ?? { items: [], next_cursor: null, total_estimate: 0, query: {} }
  });
  const facets = useQuery({
    queryKey: ["file-facets", filters],
    queryFn: () => fetchJson<FileFacets>(`/api/admin/files/facets${queryString(apiParams(filters))}`),
    placeholderData: (previousData) => previousData ?? {}
  });
  const inspection = useQuery({
    queryKey: ["file-inspection", selectedId],
    enabled: Boolean(selectedId),
    queryFn: () => fetchJson<FileInspection>(`/api/admin/files/${selectedId}/inspection`)
  });
  const addReview = useMutation({
    mutationFn: (fileId: number) => postJson<ReviewItem>(`/api/admin/files/${fileId}/review`, { review_reason: "manual_file_review" }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["file-search"] }),
        queryClient.invalidateQueries({ queryKey: ["file-facets"] }),
        queryClient.invalidateQueries({ queryKey: ["file-inspection", selectedId] }),
        queryClient.invalidateQueries({ queryKey: ["review-items"] })
      ]);
    }
  });
  const runFile = useMutation({
    mutationFn: ({ fileId, embeddingProvider, llmProvider, ocrProvider }: { fileId: number; embeddingProvider: string; llmProvider: string; ocrProvider: string }) =>
      postJson<PipelineRun>(`/api/admin/files/${fileId}/run`, {
        start: true,
        embedding_provider: embeddingProvider,
        enable_llm_tags: true,
        llm_tag_provider: llmProvider,
        ocr_fallback_provider: ocrProvider
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      await queryClient.invalidateQueries({ queryKey: ["file-inspection", selectedId] });
    }
  });

  function updateFilters(patch: Partial<FileFilters>, nextSelectedId: number | null | undefined = undefined) {
    const next = { ...filters, ...patch };
    const params = new URLSearchParams();
    for (const key of filterKeys) {
      const value = next[key];
      if (value && value !== defaultFilters[key]) {
        params.set(key, value);
      }
    }
    const targetFileId = nextSelectedId === undefined ? selectedId : nextSelectedId;
    if (targetFileId) {
      params.set("file_id", String(targetFileId));
    }
    router.replace(`${pathname}${params.toString() ? `?${params.toString()}` : ""}`, { scroll: false });
  }

  function selectFile(fileId: number | null) {
    updateFilters({}, fileId);
  }

  function fileDetailHref(fileId: number) {
    const params = new URLSearchParams();
    for (const key of filterKeys) {
      const value = filters[key];
      if (value && value !== defaultFilters[key]) {
        params.set(key, value);
      }
    }
    return `/files/${fileId}${params.toString() ? `?${params.toString()}` : ""}`;
  }

  const columns = useMemo<ColumnDef<FileSearchItem>[]>(
    () => [
      {
        accessorKey: "filename",
        header: "File",
        size: 360,
        cell: ({ row }) => (
          <PathCell title={row.original.filename} subtitle={row.original.compact_path} onClick={() => router.push(fileDetailHref(row.original.id))} />
        )
      },
      {
        id: "type",
        header: "Type",
        size: 150,
        cell: ({ row }) => (
          <div className="cellStack">
            <strong>{row.original.extension ?? "-"}</strong>
            <span>{row.original.content_class ?? "-"}</span>
          </div>
        )
      },
      {
        id: "current",
        header: "Current Result",
        size: 270,
        cell: ({ row }) => <ResultSummary file={row.original} />
      },
      {
        id: "text",
        header: "Text",
        size: 120,
        cell: ({ row }) => <TextIndicator text={row.original.text_snippet} />
      },
      {
        id: "run",
        header: "Run",
        size: 210,
        cell: ({ row }) => (
          <div className="cellStack">
            <RunContextBadge runId={row.original.latest_run_id} runKey={row.original.latest_run_key} preset={row.original.latest_run_preset_key} />
            <ProviderConfigBadge
              embeddingProvider={row.original.latest_embedding_provider}
              llmEnabled={row.original.latest_enable_llm_tags}
              llmProvider={row.original.latest_llm_tag_provider}
              ocrProvider={row.original.latest_ocr_fallback_provider}
            />
          </div>
        )
      },
      {
        id: "review",
        header: "Review",
        size: 135,
        cell: ({ row }) => row.original.review_status ?? "-"
      },
      {
        accessorKey: "updated_at",
        header: "Updated",
        size: 160,
        cell: ({ row }) => row.original.updated_at ?? "-"
      }
    ],
    [] // eslint-disable-line react-hooks/exhaustive-deps
  );
  const table = useReactTable({ data: search.data?.items ?? [], columns, getCoreRowModel: getCoreRowModel() });

  return (
    <main className="pageShell">
      <header className="pageHeader">
        <div>
          <p className="eyebrow">Files</p>
          <h1>File Explorer</h1>
          <p className="muted">Search, narrow, inspect, review, and run individual files.</p>
        </div>
        <div className="buttonRow">
          <button className="secondaryButton" onClick={() => updateFilters(defaultFilters, null)}>Clear Filters</button>
        </div>
      </header>

      <DashboardSearchToolbar searchPlaceholder="Search filename, path, OCR text" searchValue={queryText} onSearchChange={setQueryText}>
        <select aria-label="Saved searches" onChange={(event) => applySavedSearch(event.target.value)} value="">
          <option value="">Saved searches</option>
          {allSavedSearches.map((searchPreset) => (
            <option key={searchPreset.label} value={searchPreset.label}>{searchPreset.label}</option>
          ))}
        </select>
        <button className="secondaryButton" onClick={saveCurrentSearch}>Save Search</button>
        <select aria-label="Sort files" value={filters.sort} onChange={(event) => updateFilters({ sort: event.target.value })}>
          <option value="updated_desc">Newest first</option>
          <option value="updated_asc">Oldest first</option>
          <option value="filename">Filename</option>
          <option value="primary_tag">Primary tag</option>
          <option value="quality">Quality</option>
        </select>
        <span className="muted">{search.data?.total_estimate ?? 0} results</span>
      </DashboardSearchToolbar>

      <ActiveFilterChips filters={filters} defaults={defaultFilters} onRemove={(key) => updateFilters({ [key]: "" })} />

      <section className="fileExplorerLayout">
        <FacetPanel
          definitions={fileFacetDefinitions}
          facets={facets.data ?? {}}
          filters={filters}
          onToggle={(key, value) => updateFilters({ [key]: filters[key] === value ? "" : value })}
        />
        <div className="fileExplorerMain">
          <ResultTableShell error={search.isError ? `File search failed: ${search.error.message}` : null}>
            <VirtualDataTable table={table} loading={search.isLoading && !search.data} emptyText="No files match these filters." />
          </ResultTableShell>
          <FileInspector
            inspection={inspection.data}
            loading={inspection.isLoading}
            onClose={() => selectFile(null)}
            onAddReview={(fileId) => addReview.mutate(fileId)}
            addingReview={addReview.isPending}
            onRunFile={(fileId, embeddingProvider, llmProvider, ocrProvider) => runFile.mutate({ fileId, embeddingProvider, llmProvider, ocrProvider })}
            runningFile={runFile.isPending}
          />
        </div>
      </section>
    </main>
  );

  function applySavedSearch(label: string) {
    const preset = allSavedSearches.find((item) => item.label === label);
    if (preset) {
      updateFilters({ ...defaultFilters, ...preset.filters }, null);
      setQueryText(preset.filters.q ?? "");
    }
  }

  function saveCurrentSearch() {
    const label = window.prompt("Name this file search");
    if (!label?.trim()) {
      return;
    }
    const activeFilters = Object.fromEntries(
      filterKeys
        .map((key) => [key, filters[key]] as const)
        .filter(([key, value]) => value && value !== defaultFilters[key])
    ) as Partial<FileFilters>;
    const next = [...customSavedSearches.filter((item) => item.label !== label.trim()), { label: label.trim(), filters: activeFilters }];
    setCustomSavedSearches(next);
    window.localStorage.setItem("sunshine-file-saved-searches", JSON.stringify(next));
  }
}

function ResultSummary({ file }: { file: FileSearchItem }) {
  return (
    <div className="cellStack">
      <strong>{file.primary_tag ?? "-"}</strong>
      <span>{file.route_status ?? "-"}</span>
      <QualityBadge value={file.quality} />
      {file.secondary_tags.length ? <span>{file.secondary_tags.slice(0, 3).join(", ")}</span> : null}
    </div>
  );
}

function TextIndicator({ text }: { text?: string | null }) {
  if (!text) {
    return <span className="muted">No text</span>;
  }
  return (
    <span className="statusPill" title={text}>
      Text available
    </span>
  );
}

function FileInspector({
  inspection,
  loading,
  onClose,
  onAddReview,
  addingReview,
  onRunFile,
  runningFile
}: {
  inspection?: FileInspection;
  loading: boolean;
  onClose: () => void;
  onAddReview: (fileId: number) => void;
  addingReview: boolean;
  onRunFile: (fileId: number, embeddingProvider: string, llmProvider: string, ocrProvider: string) => void;
  runningFile: boolean;
}) {
  const [embeddingProvider, setEmbeddingProvider] = useState("cortex");
  const [llmProvider, setLlmProvider] = useState("cortex");
  const [ocrProvider, setOcrProvider] = useState("cortex");
  if (loading) {
    return <section className="fileInspector fileDetailPanel"><div className="empty">Loading inspection...</div></section>;
  }
  if (!inspection) {
    return <section className="fileInspector fileDetailPanel"><div className="empty">Select a file to inspect details, preview it, or run it individually.</div></section>;
  }
  const file = inspection.file;
  const result = inspection.latest_result ?? {};
  return (
    <InspectorPanel eyebrow="File Details" title={file.filename} onClose={onClose} className="fileInspector fileDetailPanel">
      <div className="fileDetailGrid">
      <section className="drawerSection">
        <h3>Identity</h3>
        <KeyValue label="Relative path" value={file.relative_path} />
        <KeyValue label="Source path" value={file.source_path} />
        <KeyValue label="Collection" value={file.source_collection ?? "-"} />
        <KeyValue label="Type" value={`${file.extension ?? "-"} / ${file.content_class ?? "-"}`} />
        <KeyValue label="Size" value={file.size_bytes == null ? "-" : `${file.size_bytes} bytes`} />
        <KeyValue label="Latest run" value={<RunContextBadge runId={file.latest_run_id} runKey={file.latest_run_key} preset={file.latest_run_preset_key} />} />
        <KeyValue
          label="Latest providers"
          value={
            <ProviderConfigBadge
              embeddingProvider={file.latest_embedding_provider}
              llmEnabled={file.latest_enable_llm_tags}
              llmProvider={file.latest_llm_tag_provider}
              ocrProvider={file.latest_ocr_fallback_provider}
            />
          }
        />
      </section>

      <section className="drawerSection">
        <h3>Actions</h3>
        <div className="providerPickerGrid">
          <ProviderSelect label="Embedding path" value={embeddingProvider} onChange={setEmbeddingProvider} />
          <ProviderSelect label="LLM tag path" value={llmProvider} onChange={setLlmProvider} />
          <ProviderSelect label="OCR fallback path" value={ocrProvider} onChange={setOcrProvider} />
        </div>
        <div className="buttonRow">
          <a className="secondaryButton" href={`/api/admin/files/${file.id}/download`} download>Download File</a>
          <Link className="secondaryButton" href={`/files/${file.id}`}>Full Viewer</Link>
          <button className="secondaryButton" onClick={() => copyText(file.source_path)}>Copy Path</button>
          <button className="secondaryButton" disabled={addingReview} onClick={() => onAddReview(file.id)}>Add To Review</button>
          <button className="secondaryButton" disabled={runningFile} onClick={() => onRunFile(file.id, embeddingProvider, llmProvider, ocrProvider)}>Run File</button>
          {inspection.actions.latest_run_report_url ? <Link className="secondaryButton" href={inspection.actions.latest_run_report_url}>Run Report</Link> : null}
        </div>
      </section>

      <details className="lazyDrawerSection wideSection" open>
        <summary>Preview</summary>
        <div className="lazyDrawerSectionBody">
          <EmbeddedPreview previewUrl={`/api/admin/files/${file.id}/preview`} filename={file.filename} mimeType={file.mime_type ?? undefined} extension={file.extension ?? undefined} />
        </div>
      </details>

      <section className="drawerSection">
        <h3>Extracted Text</h3>
        <KeyValue label="Length" value={String(inspection.text.length)} />
        <KeyValue label="OCR quality" value={String(inspection.ocr.quality ?? "-")} />
        <KeyValue label="OCR confidence" value={String(inspection.ocr.mean_confidence ?? "-")} />
        <KeyValue label="Fallback" value={String(inspection.ocr.fallback_provider ?? "-")} />
        <div className="textPreview">{inspection.text.text || inspection.text.snippet || "No text available."}</div>
      </section>

      <section className="drawerSection">
        <h3>Latest Pipeline Result</h3>
        <KeyValue label="Class" value={result.final_class ?? file.content_class ?? "-"} />
        <KeyValue label="Extraction" value={result.extraction_strategy ?? "-"} />
        <KeyValue label="Status" value={result.extraction_status ?? "-"} />
        <KeyValue label="Primary tag" value={result.top_tag_candidate ?? "-"} />
        <KeyValue label="Secondary tags" value={(result.secondary_tags ?? []).join(", ") || "-"} />
        <KeyValue label="Confidence" value={result.tag_confidence == null ? "-" : String(result.tag_confidence)} />
        <KeyValue label="Destination" value={result.destination_path ?? "-"} />
        <KeyValue label="Placement" value={result.placement_status ?? "-"} />
        <WarningList warnings={result.warnings ?? []} />
      </section>

      <section className="drawerSection">
        <h3>Review State</h3>
        <KeyValue label="Review status" value={inspection.review_item?.status ?? "-"} />
        <KeyValue label="Review reason" value={inspection.review_item?.review_reason ?? "-"} />
        <KeyValue label="Decision" value={inspection.review_item?.decision ?? "-"} />
        <KeyValue label="Correct tag" value={inspection.review_item?.correct_tag ?? "-"} />
        <KeyValue label="Golden label" value={inspection.golden_label?.correct_primary_tag ?? "-"} />
      </section>

      <details className="lazyDrawerSection">
        <summary>Raw Data</summary>
        <pre className="jsonPreview">{JSON.stringify(inspection.raw, null, 2)}</pre>
      </details>
      </div>
    </InspectorPanel>
  );
}

function ProviderSelect({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label>
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="cortex">Cortex</option>
        <option value="openai">OpenAI</option>
      </select>
    </label>
  );
}

function copyText(value: string) {
  void navigator.clipboard?.writeText(value);
}

function WarningList({ warnings }: { warnings: string[] }) {
  if (!warnings.length) {
    return <KeyValue label="Warnings" value="-" />;
  }
  return (
    <div className="keyValue">
      <span>Warnings</span>
      <strong>{warnings.slice(0, 5).join("; ")}</strong>
    </div>
  );
}

function filtersFromParams(params: URLSearchParams): FileFilters {
  return {
    ...defaultFilters,
    ...Object.fromEntries(filterKeys.map((key) => [key, params.get(key) ?? defaultFilters[key]]))
  };
}

function apiParams(filters: FileFilters, extra: Record<string, string | number> = {}) {
  return {
    ...filters,
    run_id: filters.run_id ? Number(filters.run_id) : undefined,
    ...extra
  };
}

function numberParam(value: string | null) {
  if (!value) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
