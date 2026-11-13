import { Badge, Notice } from "../../components/ui";
import type { PolicyDefinition } from "../../lib/types";

function value(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

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
            {definition.os_rules.length === 0 ? <li className="text-slate-400">none</li> : null}
            {definition.os_rules.map((r, i) => (
              <li key={i}>{[r.Field, r.Operator, r.Severity ?? r.Value].filter(Boolean).map(value).join(" ")} → <code>{value(r.Action)}</code></li>
            ))}
          </ul>
        </section>
        <section aria-label={`Software rules of ${definition.name}`}>
          <h4 className="text-xs font-semibold uppercase text-slate-500">Software rules</h4>
          <ul className="text-xs">
            {definition.software_rules.length === 0 ? <li className="text-slate-400">none</li> : null}
            {definition.software_rules.map((r, i) => (
              <li key={`${r.ProductId}-${i}`}>{r.ProductName || r.ProductId} → <code>{r.Action}</code></li>
            ))}
          </ul>
        </section>
        <section aria-label={`General settings of ${definition.name}`}>
          <h4 className="text-xs font-semibold uppercase text-slate-500">General settings</h4>
          <dl className="grid grid-cols-[auto_1fr] gap-x-2 text-xs">
            {Object.entries(definition.general_settings).map(([k, v]) => (
              <div key={k} className="contents"><dt className="text-slate-500">{k}</dt><dd className="break-all">{value(v)}</dd></div>
            ))}
          </dl>
        </section>
      </div>
    </div>
  );
}
