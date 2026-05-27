"use client";

import type { ReactNode } from "react";

export function DashboardSearchToolbar({
  searchValue,
  searchPlaceholder,
  onSearchChange,
  children
}: {
  searchValue: string;
  searchPlaceholder: string;
  onSearchChange: (value: string) => void;
  children?: ReactNode;
}) {
  return (
    <section className="dashboardSearchToolbar">
      <input className="wideSearchInput" placeholder={searchPlaceholder} value={searchValue} onChange={(event) => onSearchChange(event.target.value)} />
      {children}
    </section>
  );
}
