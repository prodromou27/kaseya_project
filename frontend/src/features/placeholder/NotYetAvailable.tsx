import { Link } from "react-router";

import { EmptyState } from "../../components/States";
import { PageHeader } from "../../components/ui";

/**
 * Honest placeholder for modules that are designed but not yet implemented. Shows no numbers: an absent
 * data source must never look like "zero findings".
 */
export function NotYetAvailablePage({ title, phase }: { title: string; phase: string }) {
  return (
    <>
      <PageHeader title={title} subtitle={`Planned for phase ${phase}`} />
      <EmptyState title="This module is not implemented yet.">
        No data source is connected for this view, so no figures are shown. Absence of data here is <strong>not</strong>{" "}
        evidence of compliance. See the project roadmap ({phase}) for scope.
      </EmptyState>
    </>
  );
}

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not found" />
      <EmptyState title="The page you requested does not exist.">
        <Link to="/" className="underline">
          Return to the dashboard
        </Link>
      </EmptyState>
    </>
  );
}
