"use client";

import { useEffect, useState } from "react";

type EmbeddedPreviewProps = {
  previewUrl: string;
  filename: string;
  mimeType?: string;
  extension?: string;
};

export function EmbeddedPreview({ previewUrl, filename, mimeType, extension }: EmbeddedPreviewProps) {
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [loading, setLoading] = useState(true);
  const [activated, setActivated] = useState(false);
  const normalizedExtension = (extension || filename.split(".").pop() || "").toLowerCase().replace(/^\./, "");
  const isPdf = mimeType === "application/pdf" || normalizedExtension === "pdf";
  const isImage = (mimeType || "").startsWith("image/") || ["jpg", "jpeg", "png", "gif", "webp"].includes(normalizedExtension);
  const isText = (mimeType || "").startsWith("text/") || ["txt", "md", "csv", "json"].includes(normalizedExtension);

  useEffect(() => {
    setLoading(true);
    setZoom(1);
    setRotation(0);
    setActivated(false);
    const loadingTimer = window.setTimeout(() => setLoading(false), 1600);
    return () => window.clearTimeout(loadingTimer);
  }, [previewUrl]);

  if (!activated) {
    return (
      <div className="previewPlaceholder">
        <p className="muted">Preview is ready to load. Files are not opened automatically when selected.</p>
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
  return (
    <div className="unsupportedPreview">
      <p className="muted">Embedded preview is not available for this file type. Use Download File when you want to save the original.</p>
    </div>
  );
}
