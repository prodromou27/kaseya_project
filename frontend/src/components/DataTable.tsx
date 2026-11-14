import { flexRender, getCoreRowModel, useReactTable, type ColumnDef, type RowSelectionState, type VisibilityState } from "@tanstack/react-table";
import { useState, type ReactNode } from "react";

import { EmptyState } from "./States";

type Props<T> = {
  caption: string;
  columns: ColumnDef<T, unknown>[];
  rows: T[];
  /** Total rows on the server (server-side pagination). */
  total?: number;
  page?: number;
  pageSize?: number;
  onPageChange?: (page: number) => void;
  emptyTitle?: string;
  emptyHint?: string;
  getRowId?: (row: T) => string;
  columnChooser?: boolean;
  selectable?: boolean;
  selectionActions?: (rows: T[]) => ReactNode;
};

/**
 * Accessible, compact table shell. Sorting/filtering/pagination are server-side; this component never
 * receives more than one page of rows.
 */
export function DataTable<T>({
  caption,
  columns,
  rows,
  total,
  page = 1,
  pageSize = 50,
  onPageChange,
  emptyTitle = "No records.",
  emptyHint,
  getRowId,
  columnChooser = false,
  selectable = false,
  selectionActions,
}: Props<T>) {
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    getRowId,
    state: { columnVisibility, rowSelection },
    onColumnVisibilityChange: setColumnVisibility,
    enableRowSelection: selectable,
    onRowSelectionChange: setRowSelection,
  });

  if (rows.length === 0) return <EmptyState title={emptyTitle}>{emptyHint}</EmptyState>;

  const pageCount = total !== undefined ? Math.max(1, Math.ceil(total / pageSize)) : 1;

  return (
    <div className="data-table overflow-hidden rounded-lg border border-slate-200 bg-white">
      {columnChooser ? (
        <details className="border-b border-slate-200 px-3 py-2 text-xs">
          <summary className="w-fit cursor-pointer font-medium text-slate-600">Columns</summary>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-2" role="group" aria-label={`${caption} columns`}>
            {table.getAllLeafColumns().map((column) => (
              <label key={column.id} className="flex items-center gap-2">
                <input type="checkbox" checked={column.getIsVisible()} onChange={column.getToggleVisibilityHandler()}
                  disabled={column.getIsVisible() && table.getVisibleLeafColumns().length === 1} />
                {typeof column.columnDef.header === "string" ? column.columnDef.header : column.id}
              </label>
            ))}
          </div>
        </details>
      ) : null}
      {/* A named scroll region needs keyboard focus so wide tables can be scrolled without a mouse. */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <div className="max-h-[60vh] overflow-auto" role="region" aria-label={`${caption} table`} tabIndex={0}>
        <table className="min-w-full text-left text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead className="sticky top-0 z-10 bg-slate-100 text-xs uppercase tracking-wide text-slate-600">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {selectable ? <th scope="col" className="w-10 px-3 py-2">
                  <input type="checkbox" aria-label="Select all rows on this page" checked={table.getIsAllRowsSelected()}
                    ref={(element) => { if (element) element.indeterminate = table.getIsSomeRowsSelected(); }}
                    onChange={table.getToggleAllRowsSelectedHandler()} />
                </th> : null}
                {group.headers.map((header) => (
                  <th key={header.id} scope="col" className="px-3 py-2 font-semibold">
                    {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-slate-100">
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="hover:bg-slate-50">
                {selectable ? <td className="px-3 py-2"><input type="checkbox" aria-label={`Select row ${row.index + 1}`}
                  checked={row.getIsSelected()} onChange={row.getToggleSelectedHandler()} /></td> : null}
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3 py-1.5 align-top">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selectable && table.getSelectedRowModel().rows.length ? <div className="flex flex-wrap items-center gap-3 border-t border-sky-200 bg-sky-50 px-3 py-2 text-xs">
        <span className="font-medium text-sky-900">{table.getSelectedRowModel().rows.length} selected on this page</span>
        <button type="button" className="btn-secondary" onClick={() => table.setRowSelection({})}>Clear selection</button>
        {selectionActions?.(table.getSelectedRowModel().rows.map((row) => row.original))}
      </div> : null}
      {total !== undefined ? (
        <nav aria-label={`${caption} pagination`} className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 px-3 py-2 text-xs text-slate-600">
          <span>
            {total} record{total === 1 ? "" : "s"} · page {page} of {pageCount}
          </span>
          {onPageChange && pageCount > 1 ? (
            <span className="flex gap-2">
              <button type="button" className="btn-secondary" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
                Previous
              </button>
              <button
                type="button"
                className="btn-secondary"
                disabled={page >= pageCount}
                onClick={() => onPageChange(page + 1)}
              >
                Next
              </button>
            </span>
          ) : null}
        </nav>
      ) : null}
    </div>
  );
}
