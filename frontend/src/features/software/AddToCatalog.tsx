import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Field } from "../../components/ui";
import { api, describeError } from "../../lib/api";

export type ProgramForCatalog = { name: string; publisher: string; versions: { version: string; devices: number }[] };

function newest(versions: string[]): string {
  const parse = (v: string) => (/^\d+(\.\d+)*/.exec(v.trim())?.[0] ?? "").split(".").filter(Boolean).map(Number);
  return [...versions].filter((v) => parse(v).length).sort((a, b) => {
    const x = parse(a), y = parse(b);
    for (let i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] ?? 0) !== (y[i] ?? 0)) return (y[i] ?? 0) - (x[i] ?? 0);
    return 0;
  })[0] ?? "";
}

/** Product name without trailing version / architecture noise: "7-Zip 24.08 (x64)" -> "7-Zip". */
function productName(name: string): string {
  return name.replace(/\([^)]*\)/g, " ").replace(/\bv?\d+(?:\.\d+)+\b/g, " ").replace(/\s+/g, " ").trim() || name;
}

/** Super admin: create a catalog entry for an installed program, pre-filled from what the estate reports. The
 * current version and its evidence link must still be confirmed - the newest version seen is only a suggestion. */
export function AddToCatalog({ program, onClose }: { program: ProgramForCatalog; onClose: () => void }) {
  const qc = useQueryClient();
  const [vendor, setVendor] = useState(program.publisher || "");
  const [product, setProduct] = useState(productName(program.name));
  const [version, setVersion] = useState(newest(program.versions.map((v) => v.version)));
  const [url, setUrl] = useState("");
  const [sourceType, setSourceType] = useState("vendor_release_notes");
  const submit = useMutation({
    mutationFn: async () => {
      const row = {
        vendor, product, reference_version: version, vendor_url: url, source_type: sourceType,
        source_checked_at: new Date().toISOString(),
        aliases: [{ name_pattern: program.name, ...(program.publisher ? { publisher_pattern: program.publisher } : {}), match_type: "exact" }],
      };
      const created = await api.post<{ id: string }>("/catalog/imports/", { rows: [row] });
      try {
        await api.post(`/catalog/imports/${created.id}/approve/`);
        return "approved" as const;
      } catch {
        return "pending" as const; // a second administrator must approve (REQUIRE_SECOND_APPROVER)
      }
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["software"] });
      void qc.invalidateQueries({ queryKey: ["catalog"] });
    },
  });
  const onSubmit = (e: FormEvent) => { e.preventDefault(); submit.mutate(); };
  return (
    <form onSubmit={onSubmit} aria-label={`Add ${program.name} to the catalog`} className="space-y-3 rounded-xl border border-sky-200 bg-sky-50/50 p-4">
      <h3 className="text-sm font-semibold text-slate-900">Add “{program.name}” to the software catalog</h3>
      <p className="text-xs text-slate-600">Installs of exactly this name{program.publisher ? ` from ${program.publisher}` : ""} are then compared with the current version you enter, for every customer.</p>
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Vendor">{(id) => <input id={id} className="input w-full" required maxLength={120} value={vendor} onChange={(e) => setVendor(e.target.value)} />}</Field>
        <Field label="Product">{(id) => <input id={id} className="input w-full" required maxLength={160} value={product} onChange={(e) => setProduct(e.target.value)} />}</Field>
        <Field label="Current version" hint="Pre-filled with the newest version seen; confirm it with the vendor.">{(id, hint) => <input id={id} aria-describedby={hint} className="input w-full" required maxLength={64} value={version} onChange={(e) => setVersion(e.target.value)} />}</Field>
        <Field label="Evidence link (https)" hint="Vendor release notes or download page for that version.">{(id, hint) => <input id={id} aria-describedby={hint} className="input w-full" type="url" required pattern="https://.*" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" />}</Field>
        <Field label="Source">{(id) => (
          <select id={id} className="input w-full" value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
            <option value="vendor_release_notes">Vendor release notes</option><option value="vendor_feed">Vendor feed</option><option value="manual_verification">Manual verification</option>
          </select>)}</Field>
      </div>
      {submit.isError ? <p role="alert" className="text-sm text-red-700">{describeError(submit.error)}</p> : null}
      {submit.data === "approved" ? <p role="status" className="text-sm text-emerald-800">Added. Versions are being compared now; the Overview updates in a moment.</p> : null}
      {submit.data === "pending" ? <p role="status" className="text-sm text-sky-800">Submitted. A second administrator approves it under Settings → Software catalog.</p> : null}
      <div className="flex gap-2">
        <button type="submit" className="btn-primary" disabled={submit.isPending || submit.isSuccess}>Add to catalog</button>
        <button type="button" className="btn-secondary" onClick={onClose}>{submit.isSuccess ? "Close" : "Cancel"}</button>
      </div>
    </form>
  );
}
