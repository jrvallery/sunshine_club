"use client";

export function ActiveFilterChips<T extends Record<string, string>>({
  filters,
  defaults,
  labels,
  onRemove
}: {
  filters: T;
  defaults: T;
  labels?: Partial<Record<keyof T, string>>;
  onRemove: (key: keyof T) => void;
}) {
  const active = (Object.keys(filters) as Array<keyof T>).filter((key) => filters[key] && filters[key] !== defaults[key]);
  if (!active.length) {
    return null;
  }
  return (
    <section className="activeFilters">
      {active.map((key) => (
        <button className="filterChip" key={String(key)} onClick={() => onRemove(key)}>
          {labels?.[key] ?? String(key).replaceAll("_", " ")}: {filters[key]} x
        </button>
      ))}
    </section>
  );
}
