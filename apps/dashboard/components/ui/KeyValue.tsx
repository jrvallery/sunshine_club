import type { ReactNode } from "react";

export function KeyValue({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="keyValue">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
