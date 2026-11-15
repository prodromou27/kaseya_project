import type { ThirdPartyPatchStatus } from "../lib/types";

/** VSA3-07: an explicit statement that deployment status is not available, so nothing implies it. It is a known
 * limit of the VSA X API, not an error, so it is shown as a quiet one-line note rather than a warning. */
export function ThirdPartyPatchNotice({ status }: { status: ThirdPartyPatchStatus | undefined }) {
  if (!status || status.state !== "UNAVAILABLE") return null;
  return (
    <p className="mb-2 flex items-start gap-1.5 text-xs text-slate-500" title={`${status.evidence} Live check: ${status.live_validation.replace(/_/g, " ").toLowerCase()}.`}>
      <span aria-hidden="true" className="mt-px inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border border-slate-300 text-[9px] font-semibold">i</span>
      <span><strong className="font-medium text-slate-600">Third-party patch deployment status: unavailable.</strong> The VSA X API does not expose it; installed versions are shown instead.</span>
    </p>
  );
}
