import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge } from "../../components/ui";
import { api } from "../../lib/api";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import type { ComplianceState, Customer } from "../../lib/types";

type Coverage = "covered" | "not_covered" | "no_policy" | "unknown";
type Counts = Record<Coverage, number>;
type Program = {
  program_key: string; program: string; publisher: string; catalog_product: string | null; reference_version: string | null;
  installs: number; outdated: number; devices: number; coverage: Counts; outdated_coverage: Counts; rule_actions: string[];
  versions: { version: string; installs: number }[]; version_count: number;
};
type Summary = {
  totals: { installs: number; outdated: number; outdated_covered: number; outdated_not_covered: number; outdated_no_policy: number; outdated_unknown: number };
  programs: Program[]; disclaimer: string;
};
type DeviceRow = {
  asset_id: string; hostname: string; group_name: string; program: string; installed_version: string; reference_version: string | null;
  version_state: ComplianceState; coverage: Coverage; rule_action: string; policy_name: string;
};

const COVERAGE_LABEL: Record<Coverage, string> = {
  covered: "Rule in patch policy", not_covered: "No rule in policy", no_policy: "No patch policy", unknown: "Policy not collected",
};
const COVERAGE_TONE: Record<Coverage, "good" | "bad" | "warn" | "neutral"> = { covered: "good", not_covered: "bad", no_policy: "bad", unknown: "neutral" };
const words = (code: string) => code.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());

function Stat({ label, value, hint, onClick, active }: { label: string; value: number; hint: string; onClick?: () => void; active?: boolean }) {
  const body = (<><span className="block text-xs font-medium text-slate-600">{label}</span><span className="mt-1 block text-2xl font-semibold tabular-nums text-slate-900">{value}</span><span className="mt-0.5 block text-xs text-slate-500">{hint}</span></>);
  return onClick ? (
    <button type="button" aria-pressed={active} onClick={onClick} className={`rounded-xl border bg-white p-4 text-left shadow-sm hover:border-sky-400 ${active ? "border-sky-400 ring-1 ring-sky-300" : "border-slate-200"}`}>{body}</button>
  ) : <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">{body}</div>;
}

function Devices({ customer, program, coverage, onClear }: { customer: Customer; program: Program | null; coverage: Coverage | ""; onClear: () => void }) {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["software", customer.id, "third-party-devices", program?.program_key ?? "", coverage, page],
    queryFn: ({ signal }) => api.get<{ count: number; page_size: number; results: DeviceRow[] }>(
      `/customers/${customer.id}/software/third-party/devices/`,
      { program: program?.program_key ?? "", coverage, version_state: "outdated", page }, signal),
  });
  const columns: ColumnDef<DeviceRow, unknown>[] = [
    { header: "Device", cell: ({ row }) => <Link className="font-medium text-sky-800 hover:underline" to={`/assets/${row.original.asset_id}`}>{row.original.hostname}</Link> },
    { header: "Group", cell: ({ row }) => row.original.group_name || "—" },
    { header: "Program", accessorKey: "program" },
    { header: "Installed", cell: ({ row }) => <span className="nowrap">{row.original.installed_version || "—"}</span> },
    { header: "Reference", cell: ({ row }) => <span className="nowrap">{row.original.reference_version ?? "—"}</span> },
    { header: "Patch policy", cell: ({ row }) => (
      <span className="flex flex-col gap-0.5">
        <Badge tone={COVERAGE_TONE[row.original.coverage]}>{COVERAGE_LABEL[row.original.coverage]}</Badge>
        <span className="text-xs text-slate-500">{[row.original.policy_name, row.original.rule_action && words(row.original.rule_action)].filter(Boolean).join(" · ")}</span>
      </span>
    ) },
  ];
  return (
    <section aria-labelledby="tp-dev-h" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="tp-dev-h" className="text-sm font-semibold text-slate-900">Outdated installations</h3>
        {program ? <button type="button" className="filter-chip" onClick={onClear}>Program: {program.program} ✕</button> : null}
        {coverage ? <span className="text-xs text-slate-600">· {COVERAGE_LABEL[coverage]}</span> : null}
      </div>
      <QueryBoundary query={query}>
        {(d) => <DataTable caption="Outdated third-party installations" columns={columns} rows={d.results} total={d.count} page={page} pageSize={d.page_size}
          onPageChange={setPage} getRowId={(r) => `${r.asset_id}-${r.program}-${r.installed_version}`} emptyTitle="No outdated installations match." />}
      </QueryBoundary>
    </section>
  );
}

/** Third-party patch exposure: catalog version state crossed with patch-policy rule coverage (configuration only). */
export function ThirdPartyPatching({ customer }: { customer: Customer }) {
  const [search, setSearch] = useState("");
  const [onlyOutdated, setOnlyOutdated] = useState(true);
  const [coverage, setCoverage] = useState<Coverage | "">("");
  const [program, setProgram] = useState<Program | null>(null);
  const term = useDebouncedValue(search, 300);
  const query = useQuery({
    queryKey: ["software", customer.id, "third-party", term, onlyOutdated],
    queryFn: ({ signal }) => api.get<Summary>(`/customers/${customer.id}/software/third-party/`, { search: term, outdated: onlyOutdated ? "true" : "" }, signal),
  });
  const pick = (c: Coverage) => setCoverage(coverage === c ? "" : c);
  const columns: ColumnDef<Program, unknown>[] = [
    { header: "Program", cell: ({ row }) => (
      <span><span className="font-medium text-slate-900">{row.original.program}</span>
        <span className="block text-xs text-slate-500">{row.original.publisher || "publisher not reported"}{row.original.catalog_product ? ` · catalog: ${row.original.catalog_product}` : " · not catalogued"}</span></span>
    ) },
    { header: "Devices", cell: ({ row }) => <span className="tabular-nums">{row.original.devices}</span> },
    { header: "Outdated", cell: ({ row }) => row.original.catalog_product ? <span className="tabular-nums font-semibold text-slate-900">{row.original.outdated}</span> : <span className="text-xs text-slate-500">not compared</span> },
    { header: "Reference", cell: ({ row }) => <span className="nowrap">{row.original.reference_version ?? "—"}</span> },
    { header: "Outdated by patch policy", cell: ({ row }) => {
      const c = row.original.outdated_coverage;
      return row.original.outdated ? (
        <span className="flex flex-wrap gap-1 text-xs">
          {(["not_covered", "no_policy", "covered", "unknown"] as Coverage[]).filter((k) => c[k]).map((k) => <Badge key={k} tone={COVERAGE_TONE[k]}>{COVERAGE_LABEL[k]}: {c[k]}</Badge>)}
        </span>
      ) : <span className="text-xs text-slate-500">—</span>;
    } },
    { header: "Policy rule action", cell: ({ row }) => <span className="text-xs">{row.original.rule_actions.map(words).join(", ") || "—"}</span> },
    { header: "", id: "open", cell: ({ row }) => row.original.outdated ? <button type="button" className="btn-secondary" onClick={() => setProgram(row.original)}>Devices</button> : null },
  ];
  return (
    <QueryBoundary query={query}>
      {(s) => (
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            Outdated versions (from the reviewed catalog) split by whether the device's VSA patch policy has a software rule for the program.
            {" "}<span className="text-slate-500">{s.disclaimer}</span>
          </p>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Stat label="Outdated installations" value={s.totals.outdated} hint={`of ${s.totals.installs} installations`} />
            <Stat label="No rule in patch policy" value={s.totals.outdated_not_covered} hint="Action needed: not handled by policy" onClick={() => pick("not_covered")} active={coverage === "not_covered"} />
            <Stat label="No patch policy" value={s.totals.outdated_no_policy} hint="Device has no patch policy" onClick={() => pick("no_policy")} active={coverage === "no_policy"} />
            <Stat label="Rule in patch policy" value={s.totals.outdated_covered} hint="Configured; deployment not reported" onClick={() => pick("covered")} active={coverage === "covered"} />
            <Stat label="Policy not collected" value={s.totals.outdated_unknown} hint="Coverage unknown" onClick={() => pick("unknown")} active={coverage === "unknown"} />
          </div>
          <div className="flex flex-wrap items-end gap-4">
            <label className="list-label">Find a program<input type="search" className="input w-72" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name or publisher" /></label>
            <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={onlyOutdated} onChange={(e) => setOnlyOutdated(e.target.checked)} />Only programs with outdated installs</label>
          </div>
          <DataTable caption="Third-party programs" columns={columns} rows={s.programs} getRowId={(p) => p.program_key}
            emptyTitle={onlyOutdated ? "No outdated programs. Programs need a catalog entry to be compared." : "No installed programs."} />
          {program || coverage ? <Devices key={`${program?.program_key ?? ""}-${coverage}`} customer={customer} program={program} coverage={coverage} onClear={() => setProgram(null)} /> : null}
        </div>
      )}
    </QueryBoundary>
  );
}
