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
} as const;
