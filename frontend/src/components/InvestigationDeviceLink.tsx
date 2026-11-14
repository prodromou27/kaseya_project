import { Link, useLocation } from "react-router";

/** Internal investigation origin is retained through device tabs and reloads. */
export function InvestigationDeviceLink({ assetId, name, tab }: { assetId: string; name: string; tab: "software" | "os-updates" }) {
  const location = useLocation();
  const query = new URLSearchParams({ tab, return_to: location.pathname + location.search });
  return <Link className="font-medium text-sky-800 hover:underline" to={`/assets/${assetId}?${query}`}>{name}</Link>;
}
