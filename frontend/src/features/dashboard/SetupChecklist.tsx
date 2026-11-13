import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { api } from "../../lib/api";
import type { Customer, Integration, Paginated } from "../../lib/types";

type Step = { done: boolean; label: string; hint: string; to: string };

/**
 * Super admin: what is still missing before any customer data can appear. Built from the live system state; hidden
 * once every step is complete.
 */
export function SetupChecklist() {
  const integrations = useQuery({
    queryKey: ["integrations"],
    queryFn: ({ signal }) => api.get<Paginated<Integration>>("/integrations/", undefined, signal),
  });
  const hosts = useQuery({
    queryKey: ["connector-hosts"],
    queryFn: ({ signal }) => api.get<{ results: unknown[]; deployment: { provider: string }[] }>("/connector-hosts/", undefined, signal),
  });
  const customers = useQuery({
    queryKey: ["customers", "setup"],
    queryFn: ({ signal }) => api.get<Paginated<Customer>>("/customers/", { page_size: 1 }, signal),
  });
  const approved = useQuery({
    queryKey: ["mappings", "approved-count"],
    queryFn: ({ signal }) => api.get<Paginated<unknown>>("/mappings/", { status: "approved", page_size: 1 }, signal),
  });
  if (integrations.isPending || hosts.isPending || customers.isPending || approved.isPending) return null;
  if (integrations.isError || hosts.isError || customers.isError || approved.isError) return null;

  const rows = integrations.data.results;
  const live = rows.filter((i) => !i.is_fixture);
  const usable = rows.filter((i) => i.is_fixture || i.credential_configured);
  const steps: Step[] = [
    {
      // An integration can only be created for an allowed host, so an existing integration also completes this step.
      done: hosts.data.results.length > 0 || hosts.data.deployment.some((d) => d.provider === "vsa_x") || rows.length > 0,
      label: "Allow your VSA X hostname",
      hint: "Administration → Integrations → Allowed API hosts",
      to: "/admin?tab=integrations",
    },
    { done: rows.length > 0, label: "Add the VSA X integration", hint: "Base URL https://<your VSA host>", to: "/admin?tab=integrations" },
    {
      done: usable.length > 0,
      label: "Enter the API credentials",
      hint: "Set credentials with a read-only token (stored encrypted)",
      to: "/admin?tab=integrations",
    },
    {
      done: rows.some((i) => i.last_test_outcome === "ok"),
      label: "Test the connection",
      hint: "Test connection must report Connected",
      to: "/admin?tab=integrations",
    },
    { done: customers.data.count > 0, label: "Create a customer", hint: "Customers → New customer", to: "/customers" },
    {
      done: approved.data.count > 0,
      label: "Map a VSA organisation to the customer and approve it",
      hint: "Discover orgs, propose the mapping, then approve it under Mapping review",
      to: "/admin?tab=mappings",
    },
    {
      done: rows.some((i) => i.enabled),
      label: "Enable the integration",
      hint: "Syncs then run on schedule, or use Sync now on the Assets page",
      to: "/admin?tab=integrations",
    },
  ];
  const remaining = steps.filter((s) => !s.done).length;
  if (remaining === 0) return null;
  return (
    <section aria-label="Setup checklist" className="mb-4 rounded border border-amber-200 bg-amber-50 p-4">
      <h2 className="text-sm font-semibold text-amber-900">
        Finish setup: {steps.length - remaining} of {steps.length} steps done
      </h2>
      <p className="mt-0.5 text-xs text-amber-900/80">
        Customer data appears after the first sync.{live.length === 0 && rows.length > 0 ? " Only demo (fixture) integrations exist so far." : ""}
      </p>
      <ol className="mt-3 space-y-1.5">
        {steps.map((s, i) => (
          <li key={s.label} className="flex items-start gap-2 text-sm">
            <span
              aria-hidden="true"
              className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${
                s.done ? "bg-emerald-600 text-white" : "border border-amber-400 bg-white text-amber-900"
              }`}
            >
              {s.done ? "✓" : i + 1}
            </span>
            <span>
              <span className="sr-only">{s.done ? "Done: " : "To do: "}</span>
              {s.done ? (
                <span className="text-slate-600 line-through decoration-slate-400">{s.label}</span>
              ) : (
                <Link to={s.to} className="font-medium text-slate-900 underline-offset-2 hover:underline">
                  {s.label}
                </Link>
              )}
              {!s.done ? <span className="block text-xs text-slate-600">{s.hint}</span> : null}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
