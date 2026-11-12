import type { ThirdPartyPatchStatus } from "../lib/types";
import { Notice } from "./ui";

/** VSA3-07: an explicit statement that deployment status is not available, so nothing implies it. */
export function ThirdPartyPatchNotice({ status }: { status: ThirdPartyPatchStatus | undefined }) {
  if (!status || status.state !== "UNAVAILABLE") return null;
  return (
    <Notice tone="warn">
      <strong>Third-party patch deployment status: unavailable.</strong> {status.message}{" "}
      <span className="text-xs">({status.evidence} Live check: {status.live_validation.replace(/_/g, " ").toLowerCase()}.)</span>
    </Notice>
  );
}
