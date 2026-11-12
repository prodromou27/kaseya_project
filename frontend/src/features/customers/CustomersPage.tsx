import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge, Field, PageHeader, statusTone } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { useMe } from "../../lib/auth";
import type { Customer, Paginated } from "../../lib/types";

const PAGE_SIZE = 50;

const columns: ColumnDef<Customer, unknown>[] = [
  {
    header: "Code",
    accessorKey: "code",
    cell: ({ row }) => (
      <Link to={`/customers/${row.original.id}`} className="font-medium text-sky-800 underline-offset-2 hover:underline">
        {row.original.code}
      </Link>
    ),
  },
  { header: "Name", accessorKey: "name" },
  { header: "Status", accessorKey: "status", cell: ({ getValue }) => <Badge tone={statusTone[String(getValue())]}>{String(getValue())}</Badge> },
  { header: "Region", accessorKey: "data_region", cell: ({ getValue }) => String(getValue() || "—") },
  {
    header: "Restricted",
    accessorKey: "restricted_data",
    cell: ({ getValue }) => (getValue() ? <Badge tone="warn">restricted</Badge> : "—"),
  },
];

function CreateCustomerForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => api.post<Customer>("/customers/", { code, name }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["customers"] });
      onDone();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <form onSubmit={submit} aria-label="Create customer" className="mb-4 flex flex-wrap items-end gap-3 rounded border border-slate-200 bg-white p-3">
      <Field label="Code" hint="2-32 chars: A-Z, 0-9, - or _">
        {(id, hint) => <input id={id} aria-describedby={hint} className="input w-36 uppercase" required value={code} onChange={(e) => setCode(e.target.value)} />}
      </Field>
      <Field label="Name">
        {(id) => <input id={id} className="input w-72" required value={name} onChange={(e) => setName(e.target.value)} />}
      </Field>
      <button type="submit" className="btn-primary" disabled={create.isPending}>
        Create
      </button>
      <button type="button" className="btn-secondary" onClick={onDone}>
        Cancel
      </button>
      {create.isError ? (
        <p role="alert" className="w-full text-sm text-red-700">
          {describeError(create.error)}
        </p>
      ) : null}
    </form>
  );
}

export function CustomersPage() {
  const me = useMe();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const query = useQuery({
    queryKey: ["customers", "list", search, page],
    queryFn: ({ signal }) => api.get<Paginated<Customer>>("/customers/", { search, page, page_size: PAGE_SIZE }, signal),
    placeholderData: (prev) => prev,
  });

  return (
    <>
      <PageHeader
        title="Customers"
        subtitle={me.is_super_admin ? "All customers (super administrator)" : "Customers you are assigned to"}
        actions={
          me.is_super_admin && !creating ? (
            <button type="button" className="btn-primary" onClick={() => setCreating(true)}>
              New customer
            </button>
          ) : null
        }
      />
      {creating ? <CreateCustomerForm onDone={() => setCreating(false)} /> : null}
      <div className="mb-3">
        <label htmlFor="customer-search" className="sr-only">
          Search customers
        </label>
        <input
          id="customer-search"
          type="search"
          placeholder="Search by code or name"
          className="input w-72"
          value={search}
          maxLength={100}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
        />
      </div>
      <QueryBoundary query={query}>
        {(data) => (
          <DataTable
            caption="Customers"
            columns={columns}
            rows={data.results}
            total={data.count}
            page={page}
            pageSize={PAGE_SIZE}
            onPageChange={setPage}
            getRowId={(c) => c.id}
            emptyTitle={search ? "No customers match your search." : "No customers available to you."}
          />
        )}
      </QueryBoundary>
    </>
  );
}
