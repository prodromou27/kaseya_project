import { flexRender, getCoreRowModel, useReactTable, type ColumnDef, type RowSelectionState, type VisibilityState } from "@tanstack/react-table";
import { useId, useState, type ReactNode } from "react";

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
  emptyHint?: ReactNode;
  getRowId?: (row: T) => string;
  columnChooser?: boolean;
  selectable?: boolean;
  selectionActions?: (rows: T[]) => ReactNode;
  visibleColumns?: string[];
  onVisibleColumnsChange?: (columns: string[]) => void;
  density?: "compact" | "comfortable";
  onDensityChange?: (density: "compact" | "comfortable") => void;
  onPageSizeChange?: (size: number) => void;
  sorting?: string;
  sortableColumns?: Record<string, string>;
  onSort?: (field: string) => void;
  loading?: boolean;
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
  visibleColumns, onVisibleColumnsChange,
  density = "compact", onDensityChange, onPageSizeChange,
  sorting = "", sortableColumns = {}, onSort, loading = false,
}: Props<T>) {
  const paginationId = useId();
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const ids = columns.map((column) => column.id ?? ("accessorKey" in column ? String(column.accessorKey) : ""));
  const visibilityKey = visibleColumns ? JSON.stringify([ids, visibleColumns]) : "uncontrolled";
  const suppliedVisibility = visibleColumns ? Object.fromEntries(ids.map((id) => [id, visibleColumns.includes(id)])) : {};
  const [columnState, setColumnState] = useState<{ key: string; visibility: VisibilityState }>({ key: visibilityKey, visibility: suppliedVisibility });
  if (columnState.key !== visibilityKey) {
    setColumnState({ key: visibilityKey, visibility: suppliedVisibility });
  }
  const visibility = columnState.key === visibilityKey ? columnState.visibility : suppliedVisibility;
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    getRowId,
    state: { columnVisibility: visibility, rowSelection },
    onColumnVisibilityChange: (updater) => {
      const next = typeof updater === "function" ? updater(visibility) : updater;
      // Reflect the checkbox immediately while a URL-backed parent completes its navigation transition.
      setColumnState({ key: visibilityKey, visibility: next });
      onVisibleColumnsChange?.(ids.filter((id) => next[id] !== false));
    },
    enableRowSelection: selectable,
    onRowSelectionChange: setRowSelection,
  });

  const pageCount = total !== undefined ? Math.max(1, Math.ceil(total / pageSize)) : 1;

  return (
    <div className="data-table overflow-hidden rounded-xl border border-slate-200 bg-white" aria-busy={loading}>
      {(columnChooser || onDensityChange) ? <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-2">
        <span className="text-xs font-medium text-slate-600">{total !== undefined ? `${total.toLocaleString()} results` : `${rows.length.toLocaleString()} records`}</span>
        {onDensityChange ? <label className="flex items-center gap-2 text-xs text-slate-600">Density<select className="input py-1" value={density} onChange={(e) => onDensityChange(e.target.value as "compact" | "comfortable")}><option value="compact">Compact</option><option value="comfortable">Comfortable</option></select></label> : null}
      </div> : null}
      {loading ? <p role="status" className="border-b border-sky-100 bg-sky-50 px-4 py-2 text-xs text-sky-800">Updating results...</p> : null}
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
      {rows.length === 0 ? <EmptyState title={emptyTitle}>{emptyHint}</EmptyState> : <>
      {/* A named scroll region needs keyboard focus so wide tables can be scrolled without a mouse. */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <div className="max-h-[60vh] overflow-auto" role="region" aria-label={`${caption} table`} tabIndex={0}>
        <table className="min-w-full text-left text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead className="sticky top-0 z-10 bg-slate-100 text-xs uppercase tracking-wide text-slate-600">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {selectable ? <th scope="col" className="w-10 px-3 py-2">
                  <input type="checkbox" aria-label="Select all rows on this page" disabled={loading} checked={table.getIsAllRowsSelected()}
                    ref={(element) => { if (element) element.indeterminate = table.getIsSomeRowsSelected(); }}
                    onChange={table.getToggleAllRowsSelectedHandler()} />
                </th> : null}
                {group.headers.map((header) => (
                  <th key={header.id} scope="col" className="px-4 py-3 font-semibold" aria-sort={sortableColumns[header.column.id] && sorting.replace(/^-/, "") === sortableColumns[header.column.id] ? (sorting.startsWith("-") ? "descending" : "ascending") : undefined}>
                    {header.isPlaceholder ? null : sortableColumns[header.column.id] && onSort ? <button type="button" className="inline-flex items-center gap-2 text-left hover:text-sky-800" onClick={() => onSort(sortableColumns[header.column.id] ?? header.column.id)}>
                      {flexRender(header.column.columnDef.header, header.getContext())}<span aria-hidden="true">{sorting.replace(/^-/, "") === sortableColumns[header.column.id] ? sorting.startsWith("-") ? "↓" : "↑" : "↕"}</span>
                    </button> : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-slate-100" inert={loading}>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="hover:bg-slate-50">
                {selectable ? <td className="px-3 py-2"><input type="checkbox" aria-label={`Select row ${row.index + 1}`}
                  disabled={loading} checked={row.getIsSelected()} onChange={row.getToggleSelectedHandler()} /></td> : null}
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className={`px-4 align-middle ${density === "comfortable" ? "py-4" : "py-2.5"}`}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      </>}
      {selectable && !loading && table.getSelectedRowModel().rows.length ? <div className="flex flex-wrap items-center gap-3 border-t border-sky-200 bg-sky-50 px-3 py-2 text-xs">
        <span className="font-medium text-sky-900">{table.getSelectedRowModel().rows.length} selected on this page</span>
        <button type="button" className="btn-secondary" onClick={() => table.setRowSelection({})}>Clear selection</button>
        {selectionActions?.(table.getSelectedRowModel().rows.map((row) => row.original))}
      </div> : null}
      {total !== undefined ? (
        <nav aria-label={`${caption} pagination`} className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 px-3 py-2 text-xs text-slate-600">
          <span>
            {total} record{total === 1 ? "" : "s"} · page {page} of {pageCount}
          </span>
          <div className="flex flex-wrap items-center gap-3">
          {onPageSizeChange ? <label className="flex items-center gap-2">Rows per page<select className="input py-1" value={pageSize} disabled={loading} onChange={(event) => onPageSizeChange(Number(event.target.value))}>{[25, 50, 100, 200].map((size) => <option key={size} value={size}>{size}</option>)}</select></label> : null}
          {onPageChange && pageCount > 1 ? (
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" className="btn-secondary" disabled={loading || page <= 1} onClick={() => onPageChange(1)}>First</button>
              <button type="button" className="btn-secondary" disabled={loading || page <= 1} onClick={() => onPageChange(page - 1)}>
                Previous
              </button>
              <button
                type="button"
                className="btn-secondary"
                disabled={loading || page >= pageCount}
                onClick={() => onPageChange(page + 1)}
              >
                Next
              </button>
              <button type="button" className="btn-secondary" disabled={loading || page >= pageCount} onClick={() => onPageChange(pageCount)}>Last</button>
              <form className="flex items-center gap-1" onSubmit={(event) => {
                event.preventDefault();
                const input = event.currentTarget.elements.namedItem("page") as HTMLInputElement;
                const value = Number(input.value);
                if (Number.isInteger(value) && value >= 1 && value <= pageCount) onPageChange(value);
              }}>
                <label className="sr-only" htmlFor={paginationId}>Go to page</label>
                <input id={paginationId} key={page} name="page" className="input w-16 py-1" type="number" min={1} max={pageCount} defaultValue={page} disabled={loading} />
                <button type="submit" className="btn-secondary" disabled={loading}>Go</button>
              </form>
            </div>
          ) : null}
          </div>
        </nav>
      ) : null}
    </div>
  );
}
