"use client";

import { useRef } from "react";
import { flexRender, Table } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";

export function VirtualDataTable<T>({
  table,
  loading,
  emptyText = "No rows found."
}: {
  table: Table<T>;
  loading?: boolean;
  emptyText?: string;
}) {
  const parentRef = useRef<HTMLDivElement | null>(null);
  const rows = table.getRowModel().rows;
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 88,
    overscan: 12
  });
  const columns = table.getVisibleLeafColumns();
  const gridTemplateColumns = columns.map((column) => `${column.getSize() || 140}px`).join(" ");
  const tableWidth = columns.reduce((total, column) => total + (column.getSize() || 140), 0);

  if (loading) {
    return <div className="empty">Loading...</div>;
  }
  if (!rows.length) {
    return <div className="empty">{emptyText}</div>;
  }

  return (
    <div className="virtualTable">
      <div className="virtualHeader" style={{ gridTemplateColumns, width: `${tableWidth}px` }}>
        {table.getHeaderGroups()[0]?.headers.map((header) => (
          <div className="virtualHeaderCell" key={header.id}>
            {flexRender(header.column.columnDef.header, header.getContext())}
          </div>
        ))}
      </div>
      <div className="virtualScroll" ref={parentRef}>
        <div className="virtualInner" style={{ height: `${virtualizer.getTotalSize()}px`, width: `${tableWidth}px` }}>
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const row = rows[virtualRow.index];
            return (
              <div
                className="virtualRow"
                key={row.id}
                style={{
                  gridTemplateColumns,
                  transform: `translateY(${virtualRow.start}px)`,
                  width: `${tableWidth}px`
                }}
              >
                {row.getVisibleCells().map((cell) => (
                  <div className="virtualCell" key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
