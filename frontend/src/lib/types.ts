export type Paginated<T> = { count: number; next: string | null; previous: string | null; results: T[] };

export type CustomerRef = { id: string; code: string; name: string };

export type Me = {
  id: string;
  email: string;
  display_name: string;
  auth_source: "local" | "oidc";
  global_role: string | null;
  global_capabilities: string[];
  is_super_admin: boolean;
  memberships: { customer: CustomerRef; role: string; capabilities: string[] }[];
};

export type AuthConfig = { local_login_enabled: boolean; oidc_enabled: boolean };

export type CustomerStatus = "onboarding" | "active" | "suspended" | "archived";

export type Customer = {
  id: string;
  code: string;
  name: string;
  status: CustomerStatus;
  data_region: string;
  restricted_data: boolean;
  notes: string;
  created_at: string;
  updated_at: string;
  my_capabilities: string[];
};

export type Membership = {
  id: string;
  user: { id: string; email: string; display_name: string; is_active: boolean };
  role: "admin" | "engineer" | "viewer";
  can_export: boolean;
  is_active: boolean;
  granted_by: string | null;
  granted_at: string;
  revoked_at: string | null;
};

export type MappingStatus = "proposed" | "approved" | "rejected" | "revoked";

export type SourceMapping = {
  id: string;
  customer: CustomerRef;
  integration_instance: string;
  integration: { id: string; name: string; provider: Provider; is_fixture: boolean };
  external_org_id: string;
  external_org_name: string;
  mapping_status: MappingStatus;
  proposed_by: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string;
  created_at: string;
};

export type Provider = "vsa_x" | "itglue" | "autotask";

export type Integration = {
  id: string;
  name: string;
  provider: Provider;
  base_url: string;
  region: string;
  credential_configured: boolean;
  /** portal = entered in the portal (encrypted); server = env/file reference. */
  credential_source: "portal" | "server" | "none";
  credential_set_at: string | null;
  credential_set_by: string | null;
  enabled: boolean;
  verify_tls: boolean;
  max_rps: string;
  installed_updates_budget: number;
  applied_policies_budget: number;
  notifications_budget: number;
  custom_fields_budget: number;
  last_test_at: string | null;
  last_test_outcome: string;
  last_test_result: Partial<ConnectionTestResult>;
  status: string;
  is_fixture: boolean;
};

export type IntegrationOption = { id: string; name: string; provider: Provider; is_fixture: boolean };

export type AuditEvent = {
  id: string;
  created_at: string;
  actor_label: string;
  action: string;
  customer: string | null;
  customer_code: string | null;
  target_type: string;
  target_id: string;
  outcome: "success" | "denied" | "failure";
  request_id: string;
  metadata: Record<string, unknown>;
};

export type ReportRun = {
  id: string;
  customer: string;
  customer_code: string;
  requested_by: string;
  report_type: string;
  title?: string;
  regenerated_from?: string | null;
  format: string;
  state: "queued" | "running" | "completed" | "failed";
  row_count: number | null;
  data_basis: string;
  error_code: string;
  created_at: string;
  completed_at: string | null;
  download_available: boolean;
};

export type PortalUser = {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  auth_source: "local" | "oidc";
  global_role: string | null;
  oidc_linked: boolean;
  last_login: string | null;
};

/** Provider catalog from GET /integrations/providers/ (what an admin must enter; secret fields are stored encrypted). */
export type ProviderSpec = {
  key: string;
  label: string;
  implemented: boolean;
  phase: string;
  base_url_help: string;
  notes: string;
  fields: { name: string; label: string; secret: boolean; max_length: number; help: string; pattern_message: string }[];
};

export const PROVIDER_LABEL: Record<Provider, string> = {
  vsa_x: "Kaseya VSA X",
  itglue: "IT Glue",
  autotask: "Autotask PSA",
};

export const CAP = {
  read: "customer.read",
  export: "customer.export",
  auditRead: "customer.audit.read",
  manageMembers: "customer.manage_members",
  proposeMappings: "customer.propose_mappings",
  sync: "customer.sync",
  manageExceptions: "customer.manage_exceptions",
} as const;

// ---------------------------------------------------------------- P1: inventory, sync, software

export type AssetRow = {
  id: string;
  external_id: string;
  hostname: string;
  description: string;
  device_type: string;
  group_name: string;
  site_external_id: string;
  site_name: string;
  group_external_id: string;
  organization_external_id: string;
  client_version: string;
  last_seen_online: string | null;
  last_seen_stale: boolean | null;
  os_name: string;
  os_version: string;
  manufacturer: string;
  model: string;
  serial_number: string;
  domain: string;
  tags: string[];
  software_status: "collected" | "not_collected";
  software_count: number | null;
  active: boolean;
  source: string;
  data_basis: "fixture" | "live";
  generation_id: string;
  as_of: string;
};

export type ComplianceState = "current" | "outdated" | "newer" | "unknown" | "unsupported" | "excluded";

export type SoftwareRow = {
  id: string;
  asset_id: string;
  hostname?: string | null;
  name: string;
  publisher: string;
  installed_version: string;
  product: string | null;
  product_id: string | null;
  channel: string | null;
  state: ComplianceState;
  reason_code: string;
  reference_version: string | null;
  catalog_revision_id: string | null;
  catalog_source_url: string | null;
  catalog_source_checked_at: string | null;
  exception_id: string | null;
};

export type AssetDetail = {
  customer?: Pick<Customer, "id" | "code" | "name">;
  details: AssetDetails | null;
  third_party_patch_status: ThirdPartyPatchStatus;
  os_updates: null | { status: DevicePatchStatus; updates: DeviceOsUpdateRow[] };
  policies: DevicePolicies | null;
  health?: (HealthRow & { thresholds: HealthThresholdValues }) | null;
  reconciliation?: DeviceReconciliation[];
  notifications?: DeviceFetchMeta & { window_days: number; items: DeviceNotificationItem[] } | null;
  custom_fields?: DeviceFetchMeta & { items: { name: string; value: string; type: string }[] } | null;
  id: string;
  external_id: string;
  active: boolean;
  in_current_dataset: boolean;
  asset: AssetRow | null;
  software: SoftwareRow[];
  history: { generation_id: string; published_at: string; hostname: string; last_seen_online: string | null;
             os_name: string; software_count: number | null; current: boolean }[];
};

export type DatasetStatus = {
  mapping_id: string;
  integration: { id: string; name: string; provider: Provider; is_fixture: boolean; enabled: boolean };
  external_org_id: string;
  dataset: string;
  status: "never_synced" | "stale" | "fresh";
  as_of: string | null;
  generation_id: string | null;
  row_count: number | null;
  data_basis: "fixture" | "live" | null;
  last_run: null | { id: string; state: string; error_code: string; created_at: string; ended_at: string | null;
                     fetched: number; quarantined: number };
};

export type ProductSummary = {
  product_id: string;
  label: string;
  channel: string;
  states: Record<ComplianceState, number>;
  installations: number;
  unique_assets: number;
  versions: { version: string; state: ComplianceState; installations: number; unique_assets: number }[];
};

export type SoftwareSummary = {
  as_of: string[];
  generation_ids: string[];
  evaluation_ids: string[];
  catalog_revision_ids: string[];
  algorithm_version: string;
  data_basis: string[];
  totals: Record<ComplianceState, number>;
  eligible_installations: number;
  comparable_installations: number;
  comparable_coverage_pct: number | null;
  version_compliance_pct: number | null;
  unique_assets_with_outdated: number;
  unique_assets_evaluated: number;
  products: ProductSummary[];
  top_unsupported: { name: string; publisher: string; installations: number; unique_assets: number }[];
  third_party_patch_status: ThirdPartyPatchStatus;
  disclaimer: string;
};

export type SoftwareExceptionRow = {
  id: string;
  product: string;
  product_label: string;
  asset: string | null;
  reason: string;
  approved_by: string;
  approved_at: string;
  expires_at: string;
  status: "active" | "revoked";
};

export type CatalogProduct = {
  id: string;
  vendor: string;
  product: string;
  edition: string;
  channel: string;
  architecture: string;
  active: boolean;
  current_reference: null | { id: string; reference_version: string; effective_at: string; vendor_url: string };
};

export type CatalogAlias = {
  id: string;
  product: string;
  name_pattern: string;
  publisher_pattern: string;
  match_type: "exact" | "prefix";
  review_status: "proposed" | "approved" | "rejected";
  created_by: string;
  reviewed_by: string | null;
};

export type CatalogImport = {
  id: string;
  state: "pending" | "approved" | "rejected";
  rows: unknown[];
  preview: { index: number; status: string; change?: string; warnings?: string[]; product?: string;
             current_reference?: string | null; new_reference?: string; errors?: unknown }[];
  created_by: string;
  created_at: string;
  reviewed_by: string | null;
};

export type QuarantineRow = {
  id: string;
  sync_run: string;
  integration: string;
  external_id: string;
  external_org_id: string;
  reason: string;
  snapshot: Record<string, string>;
  created_at: string;
};

export const STATE_LABEL: Record<ComplianceState, string> = {
  current: "Current",
  outdated: "Outdated",
  newer: "Newer than reference",
  unknown: "Unknown",
  unsupported: "Not catalogued",
  excluded: "Excluded",
};

// ---------------------------------------------------------------- P2: OS updates, reporting, history

export type UpdateStatus = "collected" | "not_collected" | "not_supported" | "not_requested" | "failed" | "carried_forward";

export const UPDATE_STATUS_LABEL: Record<UpdateStatus, string> = {
  collected: "Reported",
  not_collected: "Not collected",
  not_supported: "Not supported (non-Windows)",
  not_requested: "Not requested",
  failed: "Collection failed",
  carried_forward: "Carried forward",
};

export type OsUpdateSummary = {
  as_of: string[];
  generation_ids: string[];
  data_basis: string[];
  devices_total: number;
  available_section: Record<UpdateStatus, number>;
  devices_reporting_updates: number;
  devices_with_available_updates: number;
  devices_with_zero_available: number;
  devices_by_severity: Record<string, number>;
  devices_with_other_severity: number;
  installed_section: Record<UpdateStatus, number>;
  top_available_updates: { os_update_id: string; kb_article: string; title: string; severity: string; devices: number }[];
  freshness_note: string;
  scope_note: string;
};

export type DeviceOsUpdateRow = {
  id: string;
  asset_id: string;
  hostname: string;
  state: "available" | "installed";
  kb_article: string;
  title: string;
  severity: string;
  category: string;
  cvss_score: string | null;
  release_date: string;
  installed_at_raw: string;
  installed_status: UpdateStatus;
  installed_collected_at: string | null;
};

export type DevicePatchStatus = {
  asset_id: string;
  hostname: string;
  device_type: string;
  os_name: string;
  last_seen_online: string | null;
  update_counts: Record<string, number> | null;
  available_status: UpdateStatus;
  available_count: number | null;
  installed_status: UpdateStatus;
  installed_count: number | null;
  installed_collected_at: string | null;
  collected_at: string;
};

export type ReportTemplate = {
  key: string;
  title: string;
  description: string;
  formats: string[];
  required_capabilities: string[];
  columns: string[];
  filters: Record<string, { type: string; required: boolean; choices?: string[] }>;
  limitations: string;
};

export type ReportDefinitionRow = { id: string; name: string; report_type: string; format: string; filters: Record<string, unknown>; owner: string };

export type ReportScheduleRow = {
  id: string;
  definition: string;
  frequency: "daily" | "weekly" | "monthly";
  time_of_day: string;
  weekday: number | null;
  day_of_month: number | null;
  timezone: string;
  recipient_emails: string[];
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
};

export type SavedViewRow = { id: string; name: string; view_type: string; filters: Record<string, string>; shared: boolean; owner: string };

export type TrendPoint = {
  day: string;
  as_of: string;
  source: string;
  generation_id: string;
  data_basis: string;
  devices: number;
  software: null | { evaluation_id: string; catalog_revision_ids: string[]; algorithm_version: string; current: number;
                     outdated: number; comparable: number; eligible: number; devices_with_outdated: number | null };
  os_updates: { devices_reporting: number; devices_not_reporting: number; devices_with_available: number; devices_with_critical: number };
};

export type TrendResponse = { days: number; points: TrendPoint[]; method: string };

// ---------------------------------------------------------------- VSA1/VSA2-05: hierarchy, network, details

export type NodeCounts = {
  devices: number;
  stale: number;
  never_seen: number;
  agent_not_installed: number;
  no_network_data: number;
  no_update_data: number;
};
export type GroupTreeNode = { external_id: string; instance_id?: string; name: string; is_active: boolean | null; counts: NodeCounts };
export type SiteTreeNode = { external_id: string; name: string; groups: GroupTreeNode[]; counts: NodeCounts };
export type OrgTreeNode = {
  instance_id?: string; source?: string; external_id: string; name: string; sites: SiteTreeNode[]; counts: NodeCounts };
export type HierarchyResponse = {
  as_of: string[];
  data_basis: string[];
  hierarchy_status: string[];
  devices_without_asset: number;
  stale_days: number;
  organizations: OrgTreeNode[];
  unassigned: NodeCounts;
  note: string;
};

export type AdapterAddress = { raw: string; address: string; version: number | null; kind: string; network_cidr: string; cidr_status: string };
export type Adapter = {
  name: string;
  mac: string;
  mac_locally_administered: boolean;
  dhcp_enabled: boolean | null;
  subnet_mask: string;
  gateways: string[];
  dns_servers: string[];
  sources: string[];
  addresses: AdapterAddress[];
};

export type GroupNetwork = {
  instance_id?: string;
  group: null | { external_id: string; name: string; is_active: boolean | null; site_external_id: string; organization_external_id: string };
  group_listed: boolean;
  as_of: string[];
  data_basis: string[];
  counts: { devices: number; with_reported_addresses: number; network_not_collected: number; multi_adapter: number };
  subnets: { cidr: string; devices: number; addresses: number }[];
  addresses_without_derived_subnet: Record<string, number>;
  duplicate_ips: { address: string; devices: { asset_id: string; hostname: string; group_external_id: string }[] }[];
  mac_reuse: { mac: string; device_count: number }[];
  gateways: { value: string; adapters: number }[];
  dns_servers: { value: string; adapters: number }[];
  public_ips: { value: string; devices: number }[];
  devices: { asset_id: string; hostname: string; last_seen_online: string | null; network_status: string; public_ip: string; adapters: Adapter[] }[];
  note: string;
  flags_note: string;
  expected_subnets?: { id: string; scope_type: "site" | "group"; scope_external_id: string; cidr: string }[];
  outside_expected_subnet?: { asset_id: string; hostname: string; address: string; adapter: string; mac_locally_administered: boolean }[];
  addresses_not_evaluated_against_expectation?: number;
  address_changes?: {
    previous_generation: null | { id: string; published_at: string };
    compared_devices?: number;
    not_evaluated_reason?: string;
    devices: { asset_id: string; hostname: string; added: string[]; removed: string[] }[];
  };
  review_flags?: { flag: string; count: number; evaluated?: boolean }[];
};

export type ExpectedSubnet = {
  id: string;
  scope_type: "site" | "group";
  scope_external_id: string;
  cidr: string;
  reason: string;
  state: "proposed" | "approved" | "rejected" | "retired";
  proposed_by: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
};

export type AssetDetails = {
  network_status: string;
  public_ip: string;
  adapters: Adapter[];
  disks_status: string;
  disks: { name: string; is_system: boolean | null; free_percentage: string | null; total_value_raw: string }[];
  security_status: string;
  security: { type: string; name: string; enabled: boolean | null; up_to_date: boolean | null }[];
  group_external_id: string;
  site_name: string;
  is_agent_installed: boolean | null;
  is_mdm_enrolled: boolean | null;
  units_note: string;
};

export type ThirdPartyPatchStatus = { state: string; message: string; evidence: string; live_validation: string };

// ---------------------------------------------------------------- VSA2: onboarding reconciliation

export type Classification =
  | "MATCHED_CORRECT"
  | "MATCHED_WRONG_GROUP"
  | "MATCHED_WRONG_SITE"
  | "REVIEW_WRONG_ORGANIZATION"
  | "NOT_FOUND_IN_COMPLETE_SNAPSHOT"
  | "AMBIGUOUS"
  | "DUPLICATE_INPUT"
  | "INVALID_INPUT";

export type OnboardingSheet = { name: string; rows: number; columns: number; formula_cells_ignored: number; truncated_cells: number };

export type OnboardingUpload = {
  id: string;
  display_name: string;
  file_format: "xlsx" | "csv";
  sha256: string;
  bytes: number;
  sheets: OnboardingSheet[];
  uploaded_by: string;
  created_at: string;
  expires_at: string;
  purged_at: string | null;
  available: boolean;
};

export type OnboardingPreview = {
  sheet: string;
  header_row: number;
  headers: string[];
  fields: { key: string; label: string }[];
  identifier_fields: string[];
  suggested_mapping: Record<string, number>;
  mapping: Record<string, number>;
  data_rows: number;
  rows_with_problems: number;
  rows_without_identifier: number;
  formula_cells_ignored: number;
  truncated_cells: number;
  sample: { row: number; values: Record<string, string>; problems: Record<string, string>; has_identifier: boolean }[];
};

export type OnboardingEligibility = {
  generations: { id: string; instance: string; published_at: string | null; data_basis: string; hierarchy_status: string; row_count: number }[];
  blocked: { code: string; detail: string } | null;
  stale: boolean;
};

export type ReconciliationSummary = {
  logic_version: string;
  expected_rows: number;
  classifications: Partial<Record<Classification, number>>;
  secondary_flags: Record<string, number>;
  matched_devices: number;
  snapshot_devices: number;
  unexpected_vsa_assets: number;
  unexpected_pending_review: number;
  parameters: { offline_hours: number; stale_agent_days: number; stale_source: boolean; flags_not_evaluated: Record<string, string> };
  notes: string[];
  generation: { id: string; published_at: string; data_basis: string };
};

export type ReconciliationRun = {
  id: string;
  upload: string;
  upload_name: string;
  upload_sha256: string;
  sheet: string;
  header_row: number;
  mapping: Record<string, number>;
  mapping_hash: string;
  logic_version: string;
  generation: string;
  data_basis: string;
  stale_source_acknowledged: boolean;
  requested_by: string;
  state: "queued" | "running" | "completed" | "failed";
  error_code: string;
  summary: Partial<ReconciliationSummary>;
  created_at: string;
  completed_at: string | null;
};

export type Placement = {
  source_id: string;
  hostname: string;
  organization_id: string;
  organization: string;
  site_id: string;
  site: string;
  group_id: string;
  group: string;
  last_seen_online: string;
  agent_installed?: boolean | null;
};

export type ReconciliationResult = {
  id: string;
  kind: "expected" | "unexpected";
  row_number: number | null;
  input: Record<string, string>;
  classification: Classification | "";
  effective_classification: Classification | "";
  flags: string[];
  evidence: Record<string, unknown>;
  asset: string | null;
  actual: Partial<Placement>;
  candidates: (Placement & { asset_id: string })[];
  pending_review_row: number | null;
  review_state: "not_required" | "pending" | "decided";
  reviewed_classification: Classification | "";
  reviewed_asset: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string;
};

// ---------------------------------------------------------------- VSA3-04: patch policies

export type PatchPolicyState = "assigned" | "explicit_none" | "not_reported" | "unknown";
export type DriftState = "no_baseline" | "unknown" | "matches" | "different_policy" | "missing_policy" | "unexpected_policy";

export type PolicyDefinition = {
  policy_id?: string;
  status: "collected" | "failed";
  name: string;
  description: string;
  general_settings: Record<string, unknown>;
  os_rules: Record<string, unknown>[];
  software_rules: { ProductId?: string; ProductName?: string; Action?: string }[];
  fetched_at?: string;
  changed_since_previous?: boolean | null;
};

export type DevicePolicies = {
  collection_status: string;
  collected_at: string | null;
  patch_state: PatchPolicyState;
  patch_policy_id: string;
  patch_policy_name: string;
  applied: { type: string; id: string; name: string; profiles: { id: string; name: string; category: string }[] }[];
  definition: PolicyDefinition | null;
  note: string;
};

export type PolicySummary = {
  as_of: (string | null)[];
  data_basis: string[];
  devices: number;
  patch_states: Record<PatchPolicyState, number>;
  collection_status: Record<string, number>;
  coverage: { assigned: number; verified_denominator: number; percent: number | null; excluded_unknown: number; definition: string };
  by_policy: { policy_id: string; policy_name: string; devices: number }[];
  drift: Record<DriftState, number>;
  drift_labels: Record<DriftState, string>;
  definitions: PolicyDefinition[];
  scopes: { organizations: Record<string, string>; sites: Record<string, string>; groups: Record<string, { name: string; site: string }> };
  carried_forward_note: string;
  note: string;
};

export type PolicyDeviceRow = {
  asset_id: string;
  hostname: string;
  site_external_id: string;
  site_name: string;
  group_external_id: string;
  group_name: string;
  collection_status: string;
  collected_at: string | null;
  patch_state: PatchPolicyState;
  patch_policy_id: string;
  patch_policy_name: string;
  expected: null | { scope_type: string; scope_external_id: string; expect_no_policy: boolean; policy_id: string; policy_name: string };
  drift: DriftState;
};

export type PatchBaseline = {
  id: string;
  scope_type: "organization" | "site" | "group";
  scope_external_id: string;
  expect_no_policy: boolean;
  expected_policy_id: string;
  expected_policy_name: string;
  reason: string;
  state: "proposed" | "approved" | "rejected" | "retired";
  proposed_by: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
};

export const PATCH_STATE_LABEL: Record<PatchPolicyState, string> = {
  assigned: "Policy assigned",
  explicit_none: "No Policy (explicitly configured)",
  not_reported: "No Patch Management entry reported",
  unknown: "Unknown (not collected)",
};

// ---------------------------------------------------------------- VSA4-01/02: device health

export type HealthDimension = "connectivity" | "agent_installed" | "agent_version" | "disk" | "antivirus" | "firewall";

export type HealthThresholdValues = {
  offline_hours: number;
  stale_days: number;
  disk_warning_free_pct: number;
  disk_critical_free_pct: number;
  minimum_agent_version: string;
  source: "default" | "approved";
  approved_id: string;
};

export type HealthRow = {
  asset_id: string;
  hostname: string;
  site_external_id: string;
  site_name: string;
  group_external_id: string;
  group_name: string;
  device_type: string;
  last_seen_online: string | null;
  days_since_seen: number | null;
  snapshot_at: string;
  client_version: string;
  connectivity: string;
  agent_installed: string;
  agent_version: string;
  disk: string;
  worst_disk_free_pct: number | null;
  antivirus: string;
  firewall: string;
  patch_policy: string;
  reported_aggregates: Record<string, boolean | string | null>;
  hardware: { cpu: string; cores: string; logical_processors: string; memory_total_raw: string };
};

export type HealthSummary = {
  as_of: (string | null)[];
  data_basis: string[];
  devices: number;
  thresholds: HealthThresholdValues;
  dimensions: Record<HealthDimension, Record<string, number>>;
  labels: Record<HealthDimension, Record<string, string>>;
  by_group: ({ group_external_id: string; group_name: string; site: string; devices: number } & Record<string, number | string>)[];
  notes: string[];
};

export type HealthThresholdsRow = Omit<HealthThresholdValues, "source" | "approved_id"> & {
  id: string;
  reason: string;
  state: "proposed" | "approved" | "superseded" | "rejected";
  proposed_by: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
};

// ---------------------------------------------------------------- VSA1-01: connection test

export type RateRule = { limit: number; remaining: number | null; period_seconds: number; reset_seconds: number | null; retry_seconds: number | null };
export type ConnectionTestResult = {
  outcome: string;
  message: string;
  data_basis: "fixture" | "live";
  latency_ms: number;
  http_status?: number | null;
  retry_after_seconds?: number;
  failed_request_limits?: RateRule[];
  endpoint_limits?: { endpoint: string; rules: RateRule[] }[];
  tested_at?: string;
};

// ---------------------------------------------------------------- VSA4-04 / VSA1-05: changes + device reconciliation

export type ChangeKind = "device_added" | "device_removed" | "hostname" | "group" | "site" | "os" | "agent_version" | "agent_installed" | "ip_addresses" | "software";
export type ChangeItem = { kind: ChangeKind; from?: unknown; to?: unknown; added?: string[]; removed?: string[] };
export type SnapshotRef = { id: string; published_at: string | null; data_basis: string; devices: number };
export type ChangeSummary = {
  from: SnapshotRef;
  to: SnapshotRef;
  counts: Record<ChangeKind, number>;
  devices_compared: number;
  not_compared: { ip_addresses: number; software: number };
  note: string;
};
export type ChangeDevice = { asset_id: string; external_id: string; hostname: string; group_external_id: string; changes: ChangeItem[] };
export type ComparableSnapshot = { id: string; instance: string; published_at: string | null; state: string; is_current: boolean; row_count: number; data_basis: string };
export type DeviceReconciliation = {
  run_id: string;
  run_created_at: string;
  upload_name: string;
  kind: "expected" | "unexpected";
  row_number: number | null;
  classification: string;
  reviewed_classification: string;
  flags: string[];
  role: "matched" | "candidate" | "reviewed_match";
};

// ---------------------------------------------------------------- VSA4-03: notifications + custom fields

export type DeviceFetchMeta = { status: string; collected_at: string | null; reported: number | null; stored: number | null; dropped: number | null };
export type DeviceNotificationItem = { priority: string; occurred_at: string | null; occurred_raw: string; message: string; redactions: number };
export type NotificationRow = DeviceNotificationItem & { id: string; asset: string; hostname: string; vendor_id: string };
export type NotificationSummary = {
  as_of: (string | null)[];
  window_days: number;
  per_device_limit: number;
  devices: number;
  collection_status: Record<string, number>;
  devices_without_fetch_row: number;
  notifications: number;
  devices_with_notifications: number;
  by_priority: Record<string, number>;
  recurring: { pattern: string; count: number; devices: number }[];
  note: string;
};
export type CustomFieldAllow = {
  id: string;
  name: string;
  reason: string;
  state: "proposed" | "approved" | "rejected" | "retired";
  proposed_by: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
};

// ---------------------------------------------------------------- VSA4-05 lifecycle

export type LifecycleStatus = "end_of_support" | "ending_soon" | "supported" | "unknown";

export type LifecycleEntryRef = {
  id: string;
  label: string;
  release_label: string;
  version_prefix: string;
  edition_note: string;
  release_date: string | null;
  end_of_mainstream: string | null;
  end_of_support: string;
  extended_until: string | null;
  source_url: string;
  source_type: string;
  source_checked_at: string;
  reviewed_by: string | null;
};

export type LifecycleGroup = { status: LifecycleStatus; reason: string; entry: LifecycleEntryRef | null; reported: string; count: number };

export type LifecycleSummary = {
  evaluated_on: string;
  algorithm_version: string;
  ending_soon_days: number;
  as_of: (string | null)[];
  data_basis: string[];
  labels: Record<LifecycleStatus, string>;
  reasons: Record<string, string>;
  os: { devices: number; totals: Record<LifecycleStatus, number>; groups: LifecycleGroup[] };
  software: {
    installations: number;
    totals: Record<LifecycleStatus, number>;
    devices_with_end_of_support: number;
    groups: LifecycleGroup[];
  };
  notes: string[];
};

export type LifecycleRow = {
  asset_id: string;
  hostname: string;
  os_name?: string;
  os_version?: string;
  name?: string;
  installed_version?: string;
  product?: string | null;
  status: LifecycleStatus;
  reason: string;
  entry: LifecycleEntryRef | null;
};

export type LifecycleCatalogEntry = {
  id: string;
  kind: "os" | "software";
  os_family: string;
  product: string | null;
  product_label: string | null;
  release_label: string;
  version_prefix: string;
  edition_note: string;
  release_date: string | null;
  end_of_mainstream: string | null;
  end_of_support: string;
  extended_until: string | null;
  source_url: string;
  source_type: string;
  source_checked_at: string;
  confidence: "official" | "secondary";
  note: string;
  state: "proposed" | "approved" | "rejected" | "retired";
  created_by: string;
  created_at: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string;
};
