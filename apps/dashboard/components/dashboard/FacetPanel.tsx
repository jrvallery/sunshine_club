"use client";

export type FacetDefinition<T extends string> = {
  key: T;
  title: string;
  facetKey: string;
  valueMap?: Record<string, string>;
  limit?: number;
};

export function FacetPanel<T extends string>({
  facets,
  filters,
  definitions,
  className = "",
  onToggle
}: {
  facets: Record<string, Record<string, number>>;
  filters: Record<T, string>;
  definitions: Array<FacetDefinition<T>>;
  className?: string;
  onToggle: (key: T, value: string) => void;
}) {
  return (
    <div className={["facetPanel", className].filter(Boolean).join(" ")} tabIndex={0} aria-label="Filter facets">
      {definitions.map((definition) => {
        const values = Object.entries(facets[definition.facetKey] ?? {}).slice(0, definition.limit ?? 10);
        return (
          <section className="facetGroup" key={definition.facetKey}>
            <h2>{definition.title}</h2>
            {values.map(([rawValue, count]) => {
              const value = definition.valueMap?.[rawValue] ?? rawValue;
              return (
                <button className={filters[definition.key] === value ? "facetOption active" : "facetOption"} key={rawValue} onClick={() => onToggle(definition.key, value)}>
                  <span>{rawValue}</span>
                  <strong>{count}</strong>
                </button>
              );
            })}
            {!values.length ? <p className="muted">No values.</p> : null}
          </section>
        );
      })}
    </div>
  );
}
