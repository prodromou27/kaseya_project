import { describe, expect, it } from "vitest";

import { resultReason } from "./customfields/JobPanel";

describe("custom field result reasons", () => {
  it("explains an update VSA X accepted but did not apply, and other codes in plain language", () => {
    expect(resultReason("update_not_applied")).toMatch(/^VSA X answered OK but the device still has its previous value/);
    expect(resultReason("vsa_rejected_403")).toBe("VSA X refused the change (HTTP 403).");
    expect(resultReason("confirmed_after_timeout_or_connection")).toMatch(/reading back confirmed/);
    expect(resultReason("something_new")).toBe("something new");
    expect(resultReason("")).toBe("");
  });
});
