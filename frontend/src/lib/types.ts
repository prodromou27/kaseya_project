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
  enabled: boolean;
  verify_tls: boolean;
  max_rps: string;
  installed_updates_budget: number;
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
  os_updates: null | { status: DevicePatchStatus; updates: DeviceOsUpdateRow[] };
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
