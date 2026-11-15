import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { DataTable } from "../../components/DataTable";
import { QueryBoundary } from "../../components/States";
import { Badge, Field } from "../../components/ui";
import { api } from "../../lib/api";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import { useUrlFilters } from "../../lib/useUrlFilters";
import type { Customer, Paginated } from "../../lib/types";

export type GroupSuggestion = {
  id: string; name: string; external_id?: string; site?: string; basis?: "approved_subnet" | "observed_subnet" | "naming";
  matches: { cidr: string; addresses: string[]; basis?: string; peer_devices?: number }[];
  naming_evidence?: string[];
};

export function SuggestionEvidence({ suggestion }: { suggestion: GroupSuggestion }) {
  return <div className="space-y-1">
    {suggestion.external_id ? <p className="text-xs text-slate-500">Site {suggestion.site || "not reported"} · group ID {suggestion.external_id}</p> : null}
    <Badge tone={suggestion.basis === "naming" ? "neutral" : "info"}>{suggestion.basis === "naming" ? "Naming only" : suggestion.basis === "observed_subnet" ? "Observed subnet" : "Approved subnet"}</Badge>
    {suggestion.matches.map((match, index) => <p key={`${match.cidr}:${index}`} className="text-xs">
      {match.addresses.join(", ")} in {match.cidr}
      {match.basis === "observed_subnet" ? ` · observed on ${match.peer_devices} destination device(s), not reviewed policy` : " · administrator-approved subnet"}
    </p>)}
    {suggestion.naming_evidence?.map((text) => <p className="text-xs text-slate-500" key={text}>{text}</p>)}
  </div>;
}

type DeviceHints = { asset_id: string; hostname: string; suggestions: GroupSuggestion[]; suggestions_ambiguous: boolean };
type Response = Paginated<DeviceHints> & { is_onboarding: boolean; suggestion_note: string };

export function GroupSuggestions({ customer, groupId, instance }: { customer: Customer; groupId: string; instance: string }) {
  const { filters, update, page, setPage } = useUrlFilters({ suggestion_search: "" });
  const search = useDebouncedValue(filters.suggestion_search);
  const query = useQuery({
    queryKey: ["group-destination-suggestions", customer.id, instance, groupId, page, search],
    queryFn: ({ signal }) => api.get<Response>(`/customers/${customer.id}/groups/${groupId}/suggestions/`, { instance, page, search }, signal),
  });
  return <section aria-label="Onboarding destination suggestions" className="investigation-card my-3 space-y-3">
    <h2 className="font-semibold">Suggested destinations for onboarding devices</h2>
    <p className="text-sm">Subnet matches come first. Naming is a weaker hint. Open a device to review a proposal; an administrator transfers the agent manually.</p>
    <Field label="Find onboarding device">{(id) => <input id={id} className="input max-w-md" type="search" maxLength={100} value={filters.suggestion_search} onChange={(event) => update({ suggestion_search: event.target.value }, true)} placeholder="Device hostname" />}</Field>
    {query.isError && page > 1 ? <button type="button" className="btn-secondary" onClick={() => setPage(1)}>Return to first page</button> : null}
    <QueryBoundary query={query}>{(data) => <>
      <p className="text-xs text-slate-500">{data.suggestion_note}</p>
      <DataTable caption="Onboarding device suggestions" rows={data.results} total={data.count} page={page} onPageChange={setPage} getRowId={(row) => row.asset_id} loading={query.isFetching || search !== filters.suggestion_search}
        emptyTitle="No onboarding devices match." columns={[
          { header: "Device", cell: ({ row }) => <Link className="text-sky-800 underline" to={`/assets/${row.original.asset_id}?tab=operations`}>{row.original.hostname}</Link> },
          { header: "Suggested destinations and evidence", cell: ({ row }) => <div className="space-y-3">
            {row.original.suggestions_ambiguous ? <p className="text-xs text-amber-800">Several groups match; review all evidence.</p> : null}
            {row.original.suggestions.length ? row.original.suggestions.map((suggestion) => <div key={suggestion.id}><strong>{suggestion.name}</strong><SuggestionEvidence suggestion={suggestion} /></div>) : <p>No matching subnet or naming evidence. Placement is not classified as incorrect. Add approved subnets on destination groups to improve suggestions.</p>}
          </div> },
        ]} />
    </>}</QueryBoundary>
  </section>;
}
