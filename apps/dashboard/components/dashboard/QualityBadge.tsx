"use client";

export function QualityBadge({ value }: { value?: string | null }) {
  const text = value || "-";
  const tone = text === "poor" || text === "failed" || text === "empty" ? "danger" : text === "ok" ? "good" : "default";
  return <span className={`qualityBadge ${tone}`}>{text}</span>;
}
