import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, describeError } from "../../lib/api";
import { formatUtc } from "../../lib/format";

export const VSA_CATALOG_URL = "https://help.vsa10.kaseya.com/help/Content/1-Modules/patch-management/application-catalog.htm";

type Matched = {
  catalog_names: string[]; vendor: string; tier: string; reference_version: string; release_date: string;
  installed_names: string[]; installs: number; older: number; newer: number;
  top_versions: { version: string; installs: number }[]; warnings: string[];
};
type Result = {
  stats: { catalog_entries: number; matched_programs: number; already_current: number; not_installed: number; skipped: number };
  rows: unknown[]; matched: Matched[]; skipped: { application: string; reason: string }[]; valid: boolean;
};

type Check = {
  id: string; started_at: string; trigger: string; triggered_by: string | null; outcome: string; error_code: string;
  catalog_last_updated: string; applied: number; pending_import: string | null;
  stats: { matched_programs?: number; applied?: number; waiting_for_review?: number };
};
type Status = { enabled: boolean; checks: Check[] };

const ERRORS: Record<string, string> = {
  unreachable: "the catalog page could not be reached from the server",
  egress_blocked: "the catalog address resolved to a blocked network",
  page_format_changed: "the page layout has changed and no catalog table was found",
};

function AutoUpdateStatus() {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["catalog", "vsa-status"], queryFn: () => api.get<Status>("/catalog/imports/vsa-catalog-status/") });
  const checkNow = useMutation({
    mutationFn: () => api.post<Status>("/catalog/imports/vsa-catalog-status/"),
    onSuccess: (data) => {
      queryClient.setQueryData(["catalog", "vsa-status"], data);
      // Refresh imports/products/aliases; the status just returned is already current.
      void queryClient.invalidateQueries({ queryKey: ["catalog"], predicate: (q) => q.queryKey[1] !== "vsa-status" });
    },
  });
  const last = status.data?.checks[0];
  const describe = (c: Check) => {
    if (c.outcome === "failed") return `Failed: ${ERRORS[c.error_code] ?? c.error_code.replace(/_/g, " ")}.`;
    if (c.outcome === "disabled") return "Automatic updates are switched off on the server.";
    if (c.outcome === "no_change") return "No change: every installed catalog program is already current.";
    const waiting = c.stats.waiting_for_review ?? 0;
    return `${c.applied} version update${c.applied === 1 ? "" : "s"} applied automatically; ${waiting} waiting for approval below.`;
  };
  return (
    <div className="rounded bg-slate-50 p-2 text-sm" aria-live="polite">
      <p>
        <strong>Automatic daily update {status.data && !status.data.enabled ? "(switched off)" : "(on)"}.</strong>{" "}
        Higher versions for programs you have approved apply automatically; new programs, lower versions and anything with a
        warning wait for approval.
      </p>
      {last ? (
        <p className="mt-1">
          Last checked {formatUtc(last.started_at)}{last.trigger === "manual" && last.triggered_by ? ` by ${last.triggered_by}` : ""}
          {last.catalog_last_updated ? ` (catalog updated ${last.catalog_last_updated})` : ""}: {describe(last)}
        </p>
      ) : status.isSuccess ? <p className="mt-1">Not checked yet.</p> : null}
      <button type="button" className="btn-secondary mt-2" disabled={checkNow.isPending} onClick={() => checkNow.mutate()}>
        {checkNow.isPending ? "Checking…" : "Check now"}
      </button>
      {checkNow.isError ? <p role="alert" className="text-red-700">{describeError(checkNow.error)}</p> : null}
    </div>
  );
}

/** Paste the VSA 10 Application Catalog table; programs installed on monitored devices become a reviewed import. */
export function VsaCatalogImport() {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const match = useMutation({ mutationFn: () => api.post<Result>("/catalog/imports/from-vsa-catalog/", { text }), onSuccess: setResult });
  const submit = useMutation({
    mutationFn: (rows: unknown[]) => api.post("/catalog/imports/", { rows }),
    onSuccess: () => { setResult(null); setText(""); void queryClient.invalidateQueries({ queryKey: ["catalog"] }); },
  });
  const s = result?.stats;
  return (
    <section aria-labelledby="vsa-catalog-h" className="space-y-2 rounded border border-slate-200 bg-white p-3">
      <h3 id="vsa-catalog-h" className="text-sm font-semibold">Import from the VSA application catalog</h3>
      <p className="text-xs text-slate-500">
        Reference versions come from the <a className="text-sky-800 underline" href={VSA_CATALOG_URL} target="_blank" rel="noopener noreferrer">VSA 10 application catalog</a>:
        the version VSA’s 3rd-Party Patching deploys, which can trail the vendor’s newest release. Only programs installed on your devices are used.
      </p>
      <AutoUpdateStatus />
      <details>
      <summary className="cursor-pointer text-sm font-medium">Paste the table instead (if the server cannot reach the page)</summary>
      <div className="mt-2 space-y-2">
      <ol className="list-decimal space-y-0.5 pl-5 text-sm text-slate-700">
        <li>Open the VSA 10 application catalog, select the whole table and copy it.</li>
        <li>Paste it below and choose <strong>Match installed programs</strong>. Only programs installed on your devices are kept.</li>
        <li>Check the versions, submit, and have a different administrator approve the import.</li>
      </ol>
      <label htmlFor="vsa-catalog-text" className="sr-only">VSA application catalog table</label>
      <textarea id="vsa-catalog-text" className="input h-32 w-full font-mono text-xs" value={text}
                placeholder={"Application\tVendor\tTier\tVersion\tRelease Date\n7-zip (64-bit)\tIgor Pavlov\t2\t26.06\t2026-11-09"}
                onChange={(e) => { setText(e.target.value); setResult(null); }} />
      <div className="flex gap-2">
        <button type="button" className="btn-secondary" disabled={!text.trim() || match.isPending} onClick={() => match.mutate()}>
          {match.isPending ? "Matching…" : "Match installed programs"}
        </button>
        {result && result.rows.length ? (
          <button type="button" className="btn-primary" disabled={!result.valid || submit.isPending} onClick={() => submit.mutate(result.rows)}>
            Submit {result.rows.length} program{result.rows.length === 1 ? "" : "s"} for review
          </button>
        ) : null}
      </div>
      {match.isError ? <p role="alert" className="text-sm text-red-700">{describeError(match.error)}</p> : null}
      {submit.isError ? <p role="alert" className="text-sm text-red-700">{describeError(submit.error)}</p> : null}
      {submit.isSuccess ? <p role="status" className="text-sm text-emerald-700">Submitted. A different administrator must approve it below.</p> : null}
      {s ? (
        <p role="status" className="text-sm">
          {s.catalog_entries} catalog entries read: <strong>{s.matched_programs} installed program{s.matched_programs === 1 ? "" : "s"} to add or update</strong>,{" "}
          {s.already_current} already current, {s.not_installed} not installed on any device, {s.skipped} skipped.
        </p>
      ) : null}
      {result?.matched.length ? (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm" aria-label="Matched programs">
            <thead><tr className="text-left text-xs text-slate-500">
              <th className="py-1 pr-3">Catalog program</th><th className="pr-3">Catalog version</th><th className="pr-3">Installed as</th>
              <th className="pr-3">Installed versions</th><th>Older / newer</th>
            </tr></thead>
            <tbody>
              {result.matched.map((m) => (
                <tr key={m.catalog_names.join("|")} className="border-t border-slate-100 align-top">
                  <td className="py-1 pr-3">{m.catalog_names.join(" / ")}<span className="block text-xs text-slate-500">{m.vendor} · tier {m.tier}</span></td>
                  <td className="pr-3"><code>{m.reference_version}</code><span className="block text-xs text-slate-500">{m.release_date}</span></td>
                  <td className="pr-3 text-xs">{m.installed_names.join(", ")}</td>
                  <td className="pr-3 text-xs">{m.top_versions.map((v) => `${v.version} (${v.installs})`).join(", ")}</td>
                  <td className="text-xs">{m.older} older / {m.newer} newer
                    {m.warnings.map((w) => <span key={w} className="block text-amber-800">⚠ {w}</span>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {result?.skipped.length ? (
        <details className="text-sm"><summary className="cursor-pointer">Skipped ({result.skipped.length})</summary>
          <ul className="mt-1 space-y-0.5 text-xs">{result.skipped.map((x, i) => <li key={i}>{x.application}: {x.reason}</li>)}</ul>
        </details>
      ) : null}
      </div>
      </details>
    </section>
  );
}
