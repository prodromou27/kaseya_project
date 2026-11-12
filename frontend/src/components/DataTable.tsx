import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";

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
}: Props<T>) {
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    getRowId,
  });

  if (rows.length === 0) return <EmptyState title={emptyTitle}>{emptyHint}</EmptyState>;

  const pageCount = total !== undefined ? Math.max(1, Math.ceil(total / pageSize)) : 1;

  return (
    <div className="overflow-hidden rounded border border-slate-200 bg-white">
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead className="bg-slate-100 text-xs uppercase tracking-wide text-slate-600">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
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
      {total !== undefined ? (
        <nav aria-label={`${caption} pagination`} className="flex items-center justify-between border-t border-slate-200 px-3 py-2 text-xs text-slate-600">
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
