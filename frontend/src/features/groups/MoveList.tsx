import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link } from "react-router";

import { Badge } from "../../components/ui";
import { api, apiUpload, describeError } from "../../lib/api";
import type { Customer } from "../../lib/types";
import { moveNow, moveOutcome, type Proposal } from "./GroupMovesPage";

/**
 * MOV-02: move a list of devices to one group. Paste names / serials / device IDs or upload TXT, CSV or XLSX, choose
 * the group, check: devices not in VSA X (not onboarded), already in the group, in another organisation or ambiguous
 * are skipped. Each device is then moved with the normal one-device step (administrators) or suggested for approval.
 */
type Destination = { id: string; name: string; external_id: string; site: string; organization: string; source: string };
type Row = {
  line: number; input: string; status: string; note: string; asset_id: string | null; hostname: string;
  current_group: string; site: string; has_pending_suggestion: boolean;
};
type Check = {
  target: { id: string; name: string; external_id: string; organization: string };
  rows: Row[]; counts: Record<string, number>; to_move: number;
  execution_available: boolean; execution_unavailable_reason: string; move_now_allowed: boolean;
};
type Result = { device: string; ok: boolean; text: string };

const SKIPPED: [string, string][] = [
  ["not_in_vsa", "not in VSA X"], ["already_there", "already in the group"], ["other_organization", "other organisation"],
  ["ambiguous", "several matches"], ["stale", "inventory out of date"], ["no_group", "no group reported"],
  ["other_customer", "other customer"], ["duplicate", "listed twice"], ["invalid", "not a device name"], ["unsupported", "asset tag"],
];

export function MoveList({ customer }: { customer: Customer }) {
  const qc = useQueryClient();
  const canSuggest = customer.my_capabilities.includes("customer.group_move.propose");
  const [target, setTarget] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [onlySkipped, setOnlySkipped] = useState(false);
  const [sure, setSure] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Result[]>([]);
  const stopRef = useRef(false);
  const destinations = useQuery({
    queryKey: ["group-move-destinations", customer.id],
    queryFn: ({ signal }) => api.get<{ groups: Destination[] }>(`/customers/${customer.id}/group-moves/destinations/`, undefined, signal),
  });
  const base = `/customers/${customer.id}/group-moves`;
  const check = useMutation({
    mutationFn: () => file
      ? apiUpload<Check>(`${base}/check-list/`, file, "file", { target_group: target })
      : api.post<Check>(`${base}/check-list/`, { text, target_group: target }),
    onSuccess: () => { setResults([]); setSure(false); },
  });
  const data = check.data;
  const movable = data?.rows.filter((r) => r.status === "move" && r.asset_id) ?? [];
  const groups = destinations.data?.groups ?? [];
  const sources = new Set(groups.map((g) => g.source)).size > 1;

  const run = async (step: (r: Row) => Promise<Result>) => {
    setBusy(true);
    stopRef.current = false;
    const done: Result[] = [];
    setResults([]);
    for (const row of movable) {
      if (stopRef.current) { done.push({ device: "", ok: false, text: `Stopped: ${movable.length - done.length} device(s) were not sent.` }); break; }
      let result: Result & { stop?: boolean };
      try {
        result = await step(row);
      } catch (error) {
        result = { device: row.hostname, ok: false, text: describeError(error) };
      }
      done.push(result);
      setResults([...done]);
      if (result.stop) {
        done.push({ device: "", ok: false, text: `Stopped after this answer: the remaining ${movable.length - done.length} device(s) were not sent. Fix the cause first.` });
        break;
      }
    }
    setResults([...done]);
    setBusy(false);
    setSure(false);
    void qc.invalidateQueries({ queryKey: ["group-moves", customer.id] });
  };
  const moveAll = () => run(async (row) => {
    const outcome = moveOutcome(await moveNow(customer.id, row.asset_id ?? "", target, reason.trim()));
    return { device: row.hostname, ...outcome };
  });
  const suggestAll = () => run(async (row) => {
    await api.post<Proposal>(base + "/", { asset: row.asset_id, target_group: target, reason: reason.trim() });
    return { device: row.hostname, ok: true, text: "Suggested; waiting for an administrator" };
  });

  const shown = data ? data.rows.filter((r) => !onlySkipped || r.status !== "move") : [];
  return (
    <div className="space-y-4">
      <section aria-label="Device list" className="list-workspace space-y-3">
        <p className="text-sm text-slate-600">
          Paste device names, serial numbers or VSA device IDs (one per line), or upload a TXT, CSV or Excel file, then choose the group.
          Devices that are not onboarded in VSA X are skipped.
        </p>
        <div className="grid gap-3 lg:grid-cols-2">
          <label className="list-label">Devices
            <textarea className="input min-h-36 font-mono text-xs" value={text} disabled={Boolean(file)} maxLength={1_000_000}
              placeholder={"WS-0012\nWS-0013\nSN-4471-AB"} onChange={(e) => { setText(e.target.value); check.reset(); }} />
          </label>
          <div className="space-y-3">
            <label className="list-label">Or upload a file (TXT, CSV, XLSX)
              <input type="file" className="text-sm" accept=".txt,.csv,.xlsx" onChange={(e) => { setFile(e.target.files?.[0] ?? null); check.reset(); }} />
            </label>
            {file ? <p className="text-xs text-slate-600">Using <span className="font-medium">{file.name}</span>. A column named Hostname, Serial, FQDN or Device ID is used; otherwise the first column.</p> : null}
            <label className="list-label">Move to group
              <select className="input" value={target} onChange={(e) => { setTarget(e.target.value); check.reset(); }} disabled={destinations.isPending}>
                <option value="">{destinations.isPending ? "Loading groups…" : "Choose a group…"}</option>
                {groups.map((g) => <option key={g.id} value={g.id}>{g.name} (org {g.organization}{g.site ? ` · site ${g.site}` : ""}{sources ? ` · ${g.source}` : ""})</option>)}
              </select>
            </label>
            <button type="button" className="btn-primary" disabled={!target || (!file && !text.trim()) || check.isPending || busy} onClick={() => check.mutate()}>
              {check.isPending ? "Checking…" : "Check list"}
            </button>
            {check.isError ? <p role="alert" className="text-sm text-red-700">{describeError(check.error)}</p> : null}
            {destinations.isError ? <p role="alert" className="text-sm text-red-700">{describeError(destinations.error)}</p> : null}
          </div>
        </div>
      </section>

      {data ? (
        <section aria-label="List check" className="list-workspace space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold text-slate-900">Move to {data.target.name}:</span>
            <Badge tone={data.to_move ? "good" : "neutral"}>{data.to_move} will be moved</Badge>
            {SKIPPED.filter(([k]) => data.counts[k]).map(([k, label]) => <Badge key={k} tone={k === "not_in_vsa" ? "warn" : "neutral"}>{data.counts[k]} skipped: {label}</Badge>)}
            {data.rows.length > data.to_move ? (
              <label className="ml-auto flex items-center gap-1 text-xs text-slate-600"><input type="checkbox" checked={onlySkipped} onChange={(e) => setOnlySkipped(e.target.checked)} />Show skipped only</label>
            ) : null}
          </div>
          {data.counts.stale ? (
            <p role="alert" className="rounded bg-amber-50 px-3 py-2 text-sm text-amber-900 ring-1 ring-inset ring-amber-200">
              The inventory is out of date, so {data.counts.stale} device{data.counts.stale === 1 ? " is" : "s are"} not moved: the portal only moves devices
              whose current group it knows. Run <span className="font-medium">Sync now</span> (Devices page), then check the list again.
            </p>
          ) : null}
          <div className="max-h-96 overflow-auto rounded border border-slate-200">
            <table className="data-table w-full text-sm" aria-label="Devices in the list">
              <thead className="sticky top-0 bg-slate-50 text-left text-xs text-slate-600">
                <tr><th className="px-2 py-1.5">Line</th><th className="px-2 py-1.5">In the list</th><th className="px-2 py-1.5">Device in VSA X</th><th className="px-2 py-1.5">Current group</th><th className="px-2 py-1.5">Result</th></tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={`${r.line}-${r.input}`} className="border-t border-slate-100">
                    <td className="px-2 py-1 text-xs text-slate-500">{r.line}</td>
                    <td className="px-2 py-1 font-mono text-xs">{r.input}</td>
                    <td className="px-2 py-1">{r.asset_id ? <Link className="text-sky-800 underline" to={`/assets/${r.asset_id}`}>{r.hostname}</Link> : <span className="text-slate-400">—</span>}</td>
                    <td className="px-2 py-1 text-xs">{r.current_group || "—"}</td>
                    <td className="px-2 py-1 text-xs"><Badge tone={r.status === "move" ? "good" : r.status === "not_in_vsa" ? "warn" : "neutral"}>{r.status === "move" ? "move" : "skipped"}</Badge> {r.note}{r.has_pending_suggestion ? " (an open suggestion for this device is replaced)" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {movable.length ? (
            data.move_now_allowed ? (
              <div className="space-y-2 rounded-md bg-slate-50 p-3 text-sm ring-1 ring-inset ring-slate-200" role="group" aria-label="Move the devices">
                <label className="list-label max-w-xl">Note for the audit log (optional)
                  <input className="input" maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Finance laptops to the new site" />
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} />
                  Move {movable.length} device{movable.length === 1 ? "" : "s"} to {data.target.name} in VSA X now (the new group&apos;s policies apply)
                </label>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className="btn-primary" disabled={!sure || busy} onClick={() => void moveAll()}>Move {movable.length} device{movable.length === 1 ? "" : "s"}</button>
                  {busy ? <button type="button" className="btn-secondary" onClick={() => { stopRef.current = true; }}>Stop after the current device</button> : null}
                </div>
              </div>
            ) : canSuggest ? (
              <div className="space-y-2 rounded-md bg-slate-50 p-3 text-sm ring-1 ring-inset ring-slate-200" role="group" aria-label="Suggest the moves">
                <p className="text-xs text-slate-600">
                  {data.execution_available ? "An administrator approves and moves them under Group moves." : `Moving in VSA X is not available: ${data.execution_unavailable_reason || "not switched on."} The suggestions are recorded for an administrator.`}
                </p>
                <label className="list-label max-w-xl">Reason (at least 10 characters)
                  <input className="input" maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />
                </label>
                <button type="button" className="btn-primary" disabled={reason.trim().length < 10 || busy} onClick={() => void suggestAll()}>Suggest {movable.length} move{movable.length === 1 ? "" : "s"}</button>
              </div>
            ) : null
          ) : <p className="text-sm text-slate-600">Nothing to move: every line is skipped.</p>}

          {results.length ? (
            <ul aria-label="Move results" aria-live="polite" className="space-y-0.5 text-xs">
              {busy ? <li>Working… {results.length} of {movable.length} done</li> : null}
              {results.map((o, i) => <li key={i}>{o.device ? <><Badge tone={o.ok ? "good" : "bad"}>{o.ok ? "Done" : "Problem"}</Badge> {o.device}: </> : null}{o.text}</li>)}
            </ul>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
