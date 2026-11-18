import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { QueryBoundary } from "../../components/States";
import { Notice } from "../../components/ui";
import { api, describeError } from "../../lib/api";
import { CAP, type CfJob, type Customer, type CustomFieldDef } from "../../lib/types";
import { FieldValue } from "./CustomFieldsPage";
import { JobPanel } from "./JobPanel";

type DeviceValues = { workstation: boolean; note: string; error: string; fields: (CustomFieldDef & { value: string | null })[] };

/** Device page: editable custom fields with the value VSA X reports now, and a change through the same reviewed job. */
export function DeviceCustomFields({ customer, assetId }: { customer: Customer; assetId: string }) {
  const values = useQuery({
    queryKey: ["cf-device", customer.id, assetId],
    queryFn: ({ signal }) => api.get<DeviceValues>(`/customers/${customer.id}/custom-fields/device/${assetId}/`, undefined, signal),
  });
  const [fieldId, setFieldId] = useState("");
  const [value, setValue] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => api.post<CfJob>(`/customers/${customer.id}/custom-field-jobs/`, { field: fieldId, value, source: "device", assets: [assetId] }),
    onSuccess: (job) => setJobId(job.id),
  });
  const canAssign = customer.my_capabilities.includes(CAP.cfAssign);
  return (
    <QueryBoundary query={values}>
      {(d) => (
        <div className="space-y-3">
          {d.error ? <Notice tone="warn">{d.error}</Notice> : null}
          {d.fields.length ? (
            <table className="text-sm" aria-label="Editable custom fields">
              <thead><tr className="text-left text-xs text-slate-500"><th className="py-1 pr-4">Field</th><th className="pr-4">Type</th><th>Value in VSA X now</th></tr></thead>
              <tbody>
                {d.fields.map((f) => (
                  <tr key={f.id} className="border-t border-slate-100"><td className="py-1 pr-4">{f.name}</td><td className="pr-4">{f.type}</td>
                    <td>{f.value ?? <span className="text-slate-500">Not set</span>}</td></tr>
                ))}
              </tbody>
            </table>
          ) : <p className="text-sm text-slate-500">No custom field is editable through the portal for this device's VSA X server.</p>}
          {!d.workstation ? <p className="text-sm text-slate-600">{d.note || "Custom fields can only be changed on workstations."}</p> : null}
          {canAssign && d.workstation && d.fields.length && !jobId ? (
            <div className="space-y-2 rounded border border-slate-200 p-2">
              <FieldValue fields={d.fields} fieldId={fieldId} value={value} onField={setFieldId} onValue={setValue} />
              <button type="button" className="btn-primary" disabled={!fieldId || !value || create.isPending} onClick={() => create.mutate()}>Review change</button>
              {create.isError ? <p role="alert" className="text-sm text-red-700">{describeError(create.error)}</p> : null}
            </div>
          ) : null}
          {jobId ? <JobPanel customer={customer} jobId={jobId} onClose={() => { setJobId(null); void values.refetch(); }} /> : null}
        </div>
      )}
    </QueryBoundary>
  );
}
