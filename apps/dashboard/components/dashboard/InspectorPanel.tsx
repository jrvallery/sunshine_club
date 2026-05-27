"use client";

import type { ReactNode } from "react";

export function InspectorPanel({
  title,
  eyebrow,
  onClose,
  children,
  className = "fileInspector"
}: {
  title: string;
  eyebrow: string;
  onClose?: () => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="drawerHeader">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2>{title}</h2>
        </div>
        {onClose ? <button className="secondaryButton" onClick={onClose}>Close</button> : null}
      </div>
      {children}
    </div>
  );
}
