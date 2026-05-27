"use client";

import type { ReactNode } from "react";

export function ResultTableShell({
  children,
  error
}: {
  children: ReactNode;
  error?: string | null;
}) {
  return (
    <section className="panel resultTableShell">
      {error ? <div className="empty dangerText">{error}</div> : null}
      {children}
    </section>
  );
}
