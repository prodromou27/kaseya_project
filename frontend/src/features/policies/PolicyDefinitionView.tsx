import { Badge, Notice } from "../../components/ui";
import type { PolicyDefinition } from "../../lib/types";

/** "RebootOption" → "Reboot option". */
function label(key: string): string {
  const words = key.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/_/g, " ").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Vendor enum codes ("DO_NOT_REBOOT") read as words; anything else is shown as reported. */
function words(v: string): string {
  return /^[A-Z][A-Z0-9_]+$/.test(v) ? label(v) : v;
}

/** Readable form of a reported setting. Objects such as a schedule ({"Type":{"Text":"Schedule"},…}) show their
 * text parts; the exact raw value stays available as a tooltip. */
function value(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "string") return words(v);
  if (Array.isArray(v)) return v.map(value).join(", ") || "—";
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    if (typeof o.Text === "string") return o.Text;
    const parts = Object.entries(o).filter(([k]) => k !== "Id").map(([k, x]) => `${label(k)}: ${value(x)}`);
    return parts.join(" · ") || "—";
  }
  return String(v);
}

const raw = (v: unknown) => (typeof v === "object" && v !== null ? JSON.stringify(v) : String(v));

/** Patch policy *configuration* from VSA X. Labelled so it is never read as deployment outcome. */
export function PolicyDefinitionView({ definition }: { definition: PolicyDefinition }) {
  if (definition.status === "failed") {
    return <Notice tone="warn">The definition of this policy could not be retrieved in this sync.</Notice>;
  }
  return (
    <div className="space-y-2 text-sm">
      <p>
        <strong>{definition.name}</strong>
        {definition.description ? <span className="text-slate-500"> — {definition.description}</span> : null}{" "}
        <Badge tone="info">configuration, not deployment status</Badge>
        {definition.changed_since_previous ? <span className="ml-1"><Badge tone="warn">changed since previous sync</Badge></span> : null}
      </p>
      <div className="grid gap-3 md:grid-cols-3">
        <section aria-label={`OS rules of ${definition.name}`}>
          <h4 className="text-xs font-semibold uppercase text-slate-500">OS rules</h4>
          <ul className="text-xs">
            {definition.os_rules.length === 0 ? <li className="text-slate-500">none</li> : null}
            {definition.os_rules.map((r, i) => (
              <li key={i} title={raw(r)}>{[r.Field, r.Operator, r.Severity ?? r.Value].filter(Boolean).map(value).join(" ").toLowerCase().replace(/^./, (c) => c.toUpperCase())} → <span className="font-medium">{value(r.Action)}</span></li>
            ))}
          </ul>
        </section>
        <section aria-label={`Software rules of ${definition.name}`}>
          <h4 className="text-xs font-semibold uppercase text-slate-500">Software rules</h4>
          <ul className="text-xs">
            {definition.software_rules.length === 0 ? <li className="text-slate-500">none</li> : null}
            {definition.software_rules.map((r, i) => (
              <li key={`${r.ProductId}-${i}`} title={raw(r)}>{r.ProductName || r.ProductId} → <span className="font-medium">{value(r.Action)}</span></li>
            ))}
          </ul>
        </section>
        <section aria-label={`General settings of ${definition.name}`}>
          <h4 className="text-xs font-semibold uppercase text-slate-500">General settings</h4>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
            {Object.entries(definition.general_settings).map(([k, v]) => (
              <div key={k} className="contents"><dt className="text-slate-500" title={k}>{label(k)}</dt><dd className="break-words" title={raw(v)}>{value(v)}</dd></div>
            ))}
          </dl>
        </section>
      </div>
    </div>
  );
}
