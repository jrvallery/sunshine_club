"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { ActiveFilterChips } from "../../components/dashboard/ActiveFilterChips";
import { DashboardSearchToolbar } from "../../components/dashboard/DashboardSearchToolbar";
import { FacetPanel, type FacetDefinition } from "../../components/dashboard/FacetPanel";
import { InspectorPanel } from "../../components/dashboard/InspectorPanel";
import { OcrEvidencePanel } from "../../components/dashboard/OcrEvidencePanel";
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
            <FileResultsList
              detailHref={fileDetailHref}
              items={search.data?.items ?? []}
              loading={search.isLoading && !search.data}
              onSelect={selectFile}
              selectedId={selectedId}
            />
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

function FileResultsList({
  detailHref,
  items,
  loading,
  onSelect,
  selectedId
}: {
  detailHref: (fileId: number) => string;
  items: FileSearchItem[];
  loading?: boolean;
  onSelect: (fileId: number) => void;
  selectedId: number | null;
}) {
  if (loading) {
    return <div className="empty">Loading files...</div>;
  }
  if (!items.length) {
    return <div className="empty">No files match these filters.</div>;
  }
  return (
    <div className="fileResultsList" aria-label="File search results">
      {items.map((file) => (
        <div aria-current={selectedId === file.id ? "true" : undefined} className={selectedId === file.id ? "fileResultCard selected" : "fileResultCard"} key={file.id}>
          <button className="fileResultSelect" onClick={() => onSelect(file.id)}>
            <div className="fileResultIdentity">
              <strong title={file.filename}>{file.filename}</strong>
              <span title={file.compact_path}>{file.compact_path}</span>
            </div>
            <div className="fileResultMeta">
              <MetaBlock label="Type" value={file.extension ?? "-"} detail={file.content_class ?? "-"} />
              <div className="fileResultBlock">
                <span>Current result</span>
                <ResultSummary file={file} />
              </div>
              <div className="fileResultBlock">
                <span>Run</span>
                <RunContextBadge runId={file.latest_run_id} runKey={file.latest_run_key} preset={file.latest_run_preset_key} />
              </div>
              <div className="fileResultBlock">
                <span>Text</span>
                <TextIndicator text={file.text_snippet} />
              </div>
              <MetaBlock label="Review" value={file.review_status ?? "-"} detail={file.updated_at ?? "-"} />
            </div>
          </button>
          <Link className="fileResultOpenLink" href={detailHref(file.id)}>Open Viewer</Link>
        </div>
      ))}
    </div>
  );
}

function MetaBlock({ label, value, detail }: { label: string; value: string; detail?: string | null }) {
  return (
    <div className="fileResultBlock">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <em>{detail}</em> : null}
    </div>
  );
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
      Has text
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
        <OcrEvidencePanel
          evidence={result.ocr_evidence}
          fallbackText={inspection.text.snippet}
          finalText={inspection.text.text || inspection.text.snippet}
        />
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
