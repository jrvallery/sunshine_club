"use client";

import { flexRender, Table } from "@tanstack/react-table";

export function DataTable<T>({ table, loading, emptyText = "No rows found." }: { table: Table<T>; loading?: boolean; emptyText?: string }) {
  if (loading) {
    return <div className="empty">Loading...</div>;
  }
  if (!table.getRowModel().rows.length) {
    return <div className="empty">{emptyText}</div>;
  }
  return (
    <div className="tableWrap">
      <table>
        <thead>
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => (
                <th key={header.id}>{flexRender(header.column.columnDef.header, header.getContext())}</th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
