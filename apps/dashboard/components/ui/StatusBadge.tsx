export function StatusBadge({ value, tone }: { value: string; tone?: "danger" | "default" }) {
  return <span className={`pill ${tone === "danger" ? "danger" : ""}`}>{value}</span>;
}
