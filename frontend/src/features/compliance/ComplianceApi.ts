export type RuleKind =
  | "required_software" | "forbidden_software" | "os_min_version" | "antivirus_healthy" | "firewall_enabled"
  | "disk_free_min" | "max_days_offline" | "agent_current" | "no_outdated_software" | "no_critical_updates"
  | "patch_policy_assigned";
export type Severity = "low" | "medium" | "high";
export type RuleState = "pass" | "fail" | "unknown";

export type BaselineRule = { id?: string; kind: RuleKind; params: Record<string, string | number>; severity: Severity; label?: string };
export type Baseline = {
  id: string; name: string; description: string; enabled: boolean;
  scope_device_type: string; scope_site_external_id: string; scope_group_external_id: string;
  rules: BaselineRule[]; created_by: string; created_at: string; updated_at: string;
};
export type Totals = Record<RuleState, number>;
export type RuleSummary = { id: string; kind: RuleKind; label: string; severity: Severity; counts: Totals };
export type GroupRow = { site: string; group_external_id: string; group_name: string; score_pct: number | null } & Totals;
export type DeviceResult = {
  asset_id: string; hostname: string; site_name: string; site_external_id: string; group_name: string; group_external_id: string;
  device_type: string; status: RuleState; failed: number; failed_high: number;
  results: { rule_id: string; state: RuleState; reason: string; severity: Severity }[];
};
export type BaselineResults = {
  baseline_id: string; devices_in_scope: number; totals: Totals; score_pct: number | null; rules: RuleSummary[];
  groups: GroupRow[]; count: number; page: number; page_size: number; results: DeviceResult[];
};
export type Overview = {
  baselines: { id: string; name: string; devices_in_scope: number; totals: Totals; score_pct: number | null; rules: RuleSummary[]; groups: GroupRow[] }[];
  rule_kinds: { kind: RuleKind; label: string }[];
};

/** Parameters each rule kind takes (mirrors the backend allowlist). */
export const RULE_PARAMS: Partial<Record<RuleKind, { key: string; label: string; type: "text" | "number"; placeholder?: string; optional?: boolean }[]>> = {
  required_software: [
    { key: "name", label: "Program name contains", type: "text", placeholder: "e.g. Chrome" },
    { key: "min_version", label: "Minimum version (optional)", type: "text", placeholder: "e.g. 131", optional: true },
  ],
  forbidden_software: [{ key: "name", label: "Program name contains", type: "text", placeholder: "e.g. TeamViewer" }],
  os_min_version: [{ key: "version", label: "Minimum OS version", type: "text", placeholder: "e.g. 10.0.22631" }],
  disk_free_min: [{ key: "percent", label: "Minimum free %", type: "number", placeholder: "15" }],
  max_days_offline: [{ key: "days", label: "Maximum days since seen", type: "number", placeholder: "14" }],
};

export const STATE_LABEL: Record<RuleState, string> = { pass: "Compliant", fail: "Not compliant", unknown: "Unknown" };
export const STATE_TONE: Record<RuleState, "good" | "bad" | "warn"> = { pass: "good", fail: "bad", unknown: "warn" };
