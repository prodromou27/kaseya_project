import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { api } from "../../lib/api";
import type { Integration, Paginated } from "../../lib/types";

/**
 * Super admin: one clear call to action until VSA is connected (an enabled integration with credentials and an
 * approved organisation). Built from the live system state; disappears once data can flow.
 */
export function SetupChecklist() {
  const integrations = useQuery({
    queryKey: ["integrations"],
    queryFn: ({ signal }) => api.get<Paginated<Integration>>("/integrations/", undefined, signal),
  });
  const approved = useQuery({
    queryKey: ["mappings", "approved-count"],
    queryFn: ({ signal }) => api.get<Paginated<unknown>>("/mappings/", { status: "approved", page_size: 1 }, signal),
  });
  if (!integrations.data || !approved.data) return null;
  const rows = integrations.data.results;
  const ready = rows.some((i) => i.enabled && (i.is_fixture || i.credential_configured)) && approved.data.count > 0;
  const failing = rows.find((i) => !i.is_fixture && i.last_test_outcome && i.last_test_outcome !== "ok");
  if (ready && !failing) return null;
  return (
    <section aria-label="Get started" className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-lg border border-sky-200 bg-sky-50 p-5">
      <div>
        <h2 className="font-semibold text-slate-900">{failing ? "VSA connection problem" : "Connect VSA X to get started"}</h2>
        <p className="mt-0.5 text-sm text-slate-600">
          {failing
            ? `The last connection test for “${failing.name}” failed (${failing.last_test_outcome}). Check the address and API token.`
            : "Enter your VSA X address and a read-only API token, then pick the organisations to bring in."}
        </p>
      </div>
      <Link to={failing ? "/admin?tab=integrations" : "/setup"} className="btn-primary">
        {failing ? "Open integration settings" : "Connect VSA"}
      </Link>
    </section>
  );
}
