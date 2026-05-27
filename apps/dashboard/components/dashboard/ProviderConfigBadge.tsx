"use client";

export function ProviderConfigBadge({
  embeddingProvider,
  llmProvider,
  ocrProvider,
  llmEnabled
}: {
  embeddingProvider?: string | null;
  llmProvider?: string | null;
  ocrProvider?: string | null;
  llmEnabled?: boolean | null;
}) {
  return (
    <div className="providerConfigBadge">
      <span>Emb: {embeddingProvider || "-"}</span>
      <span>LLM: {llmEnabled ? llmProvider || "enabled" : "off"}</span>
      <span>OCR: {ocrProvider || "-"}</span>
    </div>
  );
}
