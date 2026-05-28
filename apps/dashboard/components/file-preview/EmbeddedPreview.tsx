"use client";

import { useEffect, useState } from "react";

type EmbeddedPreviewProps = {
  previewUrl: string;
  filename: string;
  mimeType?: string;
  extension?: string;
  autoLoad?: boolean;
};

export function EmbeddedPreview({ previewUrl, filename, mimeType, extension, autoLoad = false }: EmbeddedPreviewProps) {
  const normalizedExtension = (extension || filename.split(".").pop() || "").toLowerCase().replace(/^\./, "");
  const isPdf = mimeType === "application/pdf" || normalizedExtension === "pdf";
  const shouldAutoLoad = autoLoad && !isPdf;
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [loading, setLoading] = useState(true);
  const [activated, setActivated] = useState(shouldAutoLoad);
  const isImage = (mimeType || "").startsWith("image/") || ["jpg", "jpeg", "png", "gif", "webp"].includes(normalizedExtension);
  const isText = (mimeType || "").startsWith("text/") || ["txt", "md", "csv", "json"].includes(normalizedExtension);
  const isAudio = (mimeType || "").startsWith("audio/") || ["mp3", "wav", "m4a", "aac", "ogg", "flac"].includes(normalizedExtension);

  useEffect(() => {
    setLoading(true);
    setZoom(1);
    setRotation(0);
    setActivated(shouldAutoLoad);
    const loadingTimer = window.setTimeout(() => setLoading(false), 1600);
    return () => window.clearTimeout(loadingTimer);
  }, [previewUrl, shouldAutoLoad]);

  if (!activated) {
    return (
      <div className="previewPlaceholder">
        <p className="muted">{isPdf ? "PDF preview is ready. Load it only when you want to open the embedded PDF viewer." : "Preview is ready to load."}</p>
        <button className="primaryButton" onClick={() => setActivated(true)}>
          Load Preview
        </button>
      </div>
    );
  }

  if (isPdf || isText) {
    return (
      <div className="previewFrameShell">
        {loading ? <p className="previewLoading">Loading preview...</p> : null}
        <iframe className="embeddedPreview" src={previewUrl} title={`Preview ${filename}`} onLoad={() => setLoading(false)} />
      </div>
    );
  }
  if (isImage) {
    return (
      <div className="imagePreviewShell">
        <div className="buttonRow">
          <button className="secondaryButton" onClick={() => setZoom(Math.max(0.5, zoom - 0.25))}>
            Zoom Out
          </button>
          <button className="secondaryButton" onClick={() => setZoom(Math.min(3, zoom + 0.25))}>
            Zoom In
          </button>
          <button className="secondaryButton" onClick={() => setRotation((rotation + 90) % 360)}>
            Rotate
          </button>
        </div>
        {loading ? <p className="previewLoading">Loading preview...</p> : null}
        <img
          className="imagePreview"
          src={previewUrl}
          alt={filename}
          onLoad={() => setLoading(false)}
          style={{ transform: `scale(${zoom}) rotate(${rotation}deg)` }}
        />
      </div>
    );
  }
  if (isAudio) {
    return (
      <div className="audioPreviewShell">
        <p className="muted">{filename}</p>
        <audio className="audioPreview" controls preload="metadata" src={previewUrl} onLoadedMetadata={() => setLoading(false)} />
      </div>
    );
  }
  return (
    <div className="unsupportedPreview">
      <p className="muted">Embedded preview is not available for this file type. Use Download File when you want to save the original.</p>
    </div>
  );
}
