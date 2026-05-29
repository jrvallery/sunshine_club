"use client";

import { ColumnDef, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { DataTable } from "../../components/data-table/DataTable";
import { ActiveFilterChips } from "../../components/dashboard/ActiveFilterChips";
import { DashboardSearchToolbar } from "../../components/dashboard/DashboardSearchToolbar";
import { FacetPanel, type FacetDefinition } from "../../components/dashboard/FacetPanel";
import { PathCell } from "../../components/dashboard/PathCell";
import { ResultTableShell } from "../../components/dashboard/ResultTableShell";
import { fetchJson, queryString } from "../../lib/api";
import { useDebouncedValue } from "../../lib/hooks";
import type { FileFacets, FileSearchItem, FileSearchResponse } from "../../lib/types";

type FileFilters = {
  source: "postgres";
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
  "source",
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
  source: "postgres",
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
  const filters = useMemo(() => filtersFromParams(searchParams), [searchParams]);
  const selectedId = searchParams.get("file_id");
  const [queryText, setQueryText] = useState(filters.q);
  const [customSavedSearches, setCustomSavedSearches] = useState<Array<{ label: string; filters: Partial<FileFilters> }>>([]);
  const debouncedQuery = useDebouncedValue(queryText, 300);
  const allSavedSearches = useMemo(() => [...savedSearches, ...customSavedSearches], [customSavedSearches]);

  useEffect(() => {
    if (selectedId) {
      router.replace(fileDetailHref(selectedId), { scroll: false });
    }
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

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

  function updateFilters(patch: Partial<FileFilters>) {
    const next = { ...filters, ...patch };
    const params = new URLSearchParams();
    for (const key of filterKeys) {
      const value = next[key];
      if (value && value !== defaultFilters[key]) {
        params.set(key, value);
      }
    }
    router.replace(`${pathname}${params.toString() ? `?${params.toString()}` : ""}`, { scroll: false });
  }

  function fileDetailHref(fileId: number | string) {
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
        cell: ({ row }) => (
          <PathCell title={row.original.filename} subtitle={row.original.compact_path} onClick={() => router.push(fileDetailHref(row.original.id))} />
        )
      },
      {
        id: "classification",
        header: "Classification",
        cell: ({ row }) => <ClassificationSummary file={row.original} />
      },
      {
        id: "processing",
        header: "Processing",
        cell: ({ row }) => <ProcessingSummary file={row.original} />
      },
      {
        accessorKey: "updated_at",
        header: "Updated",
        size: 160,
        cell: ({ row }) => row.original.updated_at ?? "-"
      }
    ],
    [filters] // eslint-disable-line react-hooks/exhaustive-deps
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
          <button className="secondaryButton" onClick={() => updateFilters(defaultFilters)}>Clear Filters</button>
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
        <span className="pill">Postgres</span>
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
        <ResultTableShell error={search.isError ? `File search failed: ${search.error.message}` : null}>
          <DataTable table={table} loading={search.isLoading && !search.data} emptyText="No files match these filters." className="fileBrowserTable" />
        </ResultTableShell>
      </section>
    </main>
  );

  function applySavedSearch(label: string) {
    const preset = allSavedSearches.find((item) => item.label === label);
    if (preset) {
      updateFilters({ ...defaultFilters, ...preset.filters });
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

function ClassificationSummary({ file }: { file: FileSearchItem }) {
  return (
    <div className="fileMetaStack">
      <strong className="fileMetaLine primary">{formatValue(file.primary_tag)}</strong>
      <span className="fileMetaLine">{formatFileType(file.extension, file.content_class)}</span>
      <span className="fileMetaLine">Quality: {formatStatus(file.quality)}</span>
      <span className="fileMetaLine">Action: {formatStatus(file.route_status)}</span>
    </div>
  );
}

function ProcessingSummary({ file }: { file: FileSearchItem }) {
  return (
    <div className="fileMetaStack">
      <RunSummary file={file} />
      <span className="fileMetaLine">Review: {formatStatus(file.review_status ?? "No review")}</span>
      <span className="fileMetaLine spacer" aria-hidden="true" />
      <TextIndicator text={file.text_snippet} />
    </div>
  );
}

function TextIndicator({ text }: { text?: string | null }) {
  if (!text) {
    return <span className="fileMetaLine">Text: none</span>;
  }
  return <span className="fileMetaLine" title={text}>Text: available</span>;
}

function RunSummary({ file }: { file: FileSearchItem }) {
  if (!file.latest_run_id) {
    return <span className="fileMetaLine">Run: Manual / legacy</span>;
  }
  const runHrefId = file.latest_run_key || file.latest_run_id;
  return (
    <span className="fileMetaLine">
      Run:{" "}
      <Link className="viewLink" href={`/runs/${runHrefId}/report`}>
        {file.latest_run_key || `#${file.latest_run_id}`}
      </Link>
      {file.latest_run_preset_key ? <span className="muted"> / {file.latest_run_preset_key}</span> : null}
    </span>
  );
}

function formatFileType(extension?: string | null, contentClass?: string | null) {
  return [extension, contentClass].filter(Boolean).join(" ") || "-";
}

function formatStatus(value?: string | null) {
  return formatValue(value).replace(/_/g, " ");
}

function formatValue(value?: string | null) {
  return value?.trim() || "-";
}

function filtersFromParams(params: URLSearchParams): FileFilters {
  return {
    ...defaultFilters,
    ...Object.fromEntries(filterKeys.map((key) => [key, params.get(key) ?? defaultFilters[key]])),
    source: "postgres"
  };
}

function apiParams(filters: FileFilters, extra: Record<string, string | number> = {}) {
  return {
    ...filters,
    source: "postgres",
    run_id: filters.run_id || undefined,
    ...extra
  };
}
