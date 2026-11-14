from __future__ import annotations

import uuid

from django.db import models


class GroupMoveRequest(models.Model):
    """Internal approval record only. No vendor operation is implemented or enabled."""

    class State(models.TextChoices):
        PENDING = "pending", "Awaiting independent review"
        APPROVED = "approved", "Approved proposal (execution disabled)"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="group_move_requests")
    asset = models.ForeignKey("inventory.Asset", on_delete=models.PROTECT, related_name="group_move_requests")
    generation = models.ForeignKey("integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="+")
    target_group = models.ForeignKey("inventory.GroupNode", on_delete=models.PROTECT, related_name="+")
    source_group_id = models.CharField(max_length=64)
    source_group_name = models.CharField(max_length=255, blank=True)
    device_name = models.CharField(max_length=255, blank=True)
    reason = models.CharField(max_length=1000)
    policy_impact = models.TextField()
    requested_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="group_moves_requested")
    reviewed_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, null=True, blank=True, related_name="group_moves_reviewed"
    )
    state = models.CharField(max_length=16, choices=State.choices, default=State.PENDING)
    review_reason = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [models.Index(fields=["customer", "state", "created_at"], name="inventory_move_review_idx")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(reviewed_by__isnull=True) | ~models.Q(reviewed_by=models.F("requested_by")),
                name="inventory_move_separate_review",
            ),
            models.CheckConstraint(
                condition=models.Q(state="pending", reviewed_by__isnull=True, reviewed_at__isnull=True)
                | models.Q(state__in=["approved", "rejected"], reviewed_by__isnull=False, reviewed_at__isnull=False),
                name="inventory_move_review_state",
            ),
        ]

    def __str__(self) -> str:
        return f"Group move proposal {self.id} ({self.state})"


class Asset(models.Model):
    """Stable identity of a source device. Descriptive data lives in per-generation ``AssetObservation`` rows.

    ``(integration_instance, external_id)`` is unique: a vendor ID is never re-attributed to another customer
    (a conflicting record is quarantined instead).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="assets")
    integration_instance = models.ForeignKey(
        "integrations.IntegrationInstance", on_delete=models.PROTECT, related_name="assets"
    )
    external_id = models.CharField(max_length=128)
    active = models.BooleanField(default=True, help_text="False once absent from a complete, published inventory.")
    last_generation = models.ForeignKey(
        "integrations.DatasetGeneration", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["integration_instance", "external_id"], name="inventory_asset_source_unique"
            )
        ]
        indexes = [models.Index(fields=["customer", "active"], name="inventory_asset_cust_act_idx")]

    def __str__(self) -> str:
        return f"{self.integration_instance_id}:{self.external_id}"


class AssetObservation(models.Model):
    class SoftwareStatus(models.TextChoices):
        COLLECTED = "collected", "Collected"
        NOT_COLLECTED = "not_collected", "Not collected (section absent)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="observations")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    generation = models.ForeignKey(
        "integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="asset_observations"
    )
    hostname = models.CharField(max_length=255, blank=True)
    description = models.CharField(max_length=255, blank=True)
    device_type = models.CharField(max_length=64, blank=True)
    group_name = models.CharField(max_length=255, blank=True)
    site_external_id = models.CharField(max_length=64, blank=True)
    organization_external_id = models.CharField(max_length=64)
    computer_id = models.CharField(max_length=64, blank=True)
    client_version = models.CharField(max_length=64, blank=True)
    last_seen_online = models.DateTimeField(null=True, blank=True)
    os_name = models.CharField(max_length=255, blank=True)
    os_version = models.CharField(max_length=64, blank=True)
    manufacturer = models.CharField(max_length=255, blank=True)
    model = models.CharField(max_length=255, blank=True)
    serial_number = models.CharField(max_length=255, blank=True)
    domain = models.CharField(max_length=255, blank=True)
    tags = models.JSONField(default=list, blank=True)
    software_status = models.CharField(max_length=16, choices=SoftwareStatus.choices)
    software_count = models.PositiveIntegerField(null=True, blank=True)
    # VSA1-02/04: group membership from GET /api/v3/devices; network/disk/security asset sections.
    group_external_id = models.CharField(max_length=64, blank=True, help_text="Blank = not in the device list.")
    site_name = models.CharField(max_length=255, blank=True)
    is_agent_installed = models.BooleanField(null=True)
    is_mdm_enrolled = models.BooleanField(null=True)
    public_ip = models.CharField(max_length=64, blank=True)
    network_status = models.CharField(max_length=16, default="not_collected")
    disks_status = models.CharField(max_length=16, default="not_collected")
    security_status = models.CharField(max_length=16, default="not_collected")
    # VSA4-02: hardware inventory and aggregate security flags as reported (units/encodings kept verbatim).
    memory_total_raw = models.CharField(max_length=32, blank=True, help_text="VSA MemoryTotal; units undocumented.")
    cpu_name = models.CharField(max_length=255, blank=True)
    cpu_cores_raw = models.CharField(max_length=16, blank=True)
    logical_processors_raw = models.CharField(max_length=16, blank=True)
    firewall_enabled = models.BooleanField(null=True)
    uac_enabled = models.BooleanField(null=True)
    antivirus_enabled_raw = models.CharField(max_length=32, blank=True)
    antivirus_up_to_date_raw = models.CharField(max_length=32, blank=True)
    collected_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["asset", "generation"], name="inventory_observation_asset_gen_unique")
        ]
        indexes = [
            models.Index(fields=["generation", "hostname"], name="inventory_obs_gen_host_idx"),
            models.Index(fields=["customer", "last_seen_online"], name="inventory_obs_cust_seen"),
            models.Index(fields=["generation", "group_name"], name="inventory_obs_gen_group"),
            models.Index(fields=["generation", "group_external_id"], name="inventory_obs_gen_gid"),
        ]

    def __str__(self) -> str:
        return f"{self.hostname} @ {self.generation_id}"


# ---------------------------------------------------------------------------------------------- VSA1-02 / VSA1-06


class SectionStatus(models.TextChoices):
    COLLECTED = "collected", "Collected"
    NOT_COLLECTED = "not_collected", "Not collected (section absent)"


class OrganizationNode(models.Model):
    """VSA organisation as observed in one generation. Names are labels; ``external_id`` is the key."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    generation = models.ForeignKey("integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="org_nodes")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    external_id = models.CharField(max_length=64)
    name = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["generation", "external_id"], name="inventory_orgnode_unique")]

    def __str__(self) -> str:
        return f"org {self.external_id}"


class SiteNode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    generation = models.ForeignKey(
        "integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="site_nodes"
    )
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    external_id = models.CharField(max_length=64)
    name = models.CharField(max_length=255, blank=True)
    organization_external_id = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["generation", "external_id"], name="inventory_sitenode_unique")]

    def __str__(self) -> str:
        return f"site {self.external_id}"


class GroupNode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    generation = models.ForeignKey(
        "integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="group_nodes"
    )
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    external_id = models.CharField(max_length=64)
    name = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(null=True)
    site_external_id = models.CharField(max_length=64, blank=True)
    organization_external_id = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["generation", "external_id"], name="inventory_groupnode_unique")]
        indexes = [models.Index(fields=["generation", "site_external_id"], name="inventory_group_gen_site_idx")]

    def __str__(self) -> str:
        return f"group {self.external_id}"


# ---------------------------------------------------------------------------------------------- VSA1-04


class NetworkAdapterObservation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    observation = models.ForeignKey(AssetObservation, on_delete=models.CASCADE, related_name="adapters")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="+")
    generation = models.ForeignKey("integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=255, blank=True)
    mac = models.CharField(max_length=12, blank=True)
    mac_locally_administered = models.BooleanField(default=False)
    dhcp_enabled = models.BooleanField(null=True)
    subnet_mask = models.CharField(max_length=45, blank=True)
    gateways = models.JSONField(default=list)
    dns_servers = models.JSONField(default=list)
    sources = models.JSONField(default=list, help_text="VSA sections this adapter was assembled from.")

    class Meta:
        indexes = [models.Index(fields=["generation", "mac"], name="inventory_nic_gen_mac_idx")]

    def __str__(self) -> str:
        return f"{self.name} {self.mac}"


class IpAddressObservation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    adapter = models.ForeignKey(NetworkAdapterObservation, on_delete=models.CASCADE, related_name="ips")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="+")
    generation = models.ForeignKey("integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="+")
    raw = models.CharField(max_length=64)
    address = models.CharField(max_length=45, blank=True, help_text="Canonical form without zone; blank if invalid.")
    zone = models.CharField(max_length=32, blank=True)
    version = models.PositiveSmallIntegerField(null=True)
    kind = models.CharField(max_length=16)
    prefix_length = models.PositiveSmallIntegerField(null=True)
    network_cidr = models.CharField(max_length=49, blank=True)
    cidr_status = models.CharField(max_length=24)

    class Meta:
        indexes = [
            models.Index(fields=["customer", "generation", "address"], name="inventory_ip_cust_gen_addr"),
            models.Index(fields=["generation", "network_cidr"], name="inventory_ip_gen_cidr_idx"),
        ]

    def __str__(self) -> str:
        return self.raw


class DiskObservation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    observation = models.ForeignKey(AssetObservation, on_delete=models.CASCADE, related_name="disks")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="+")
    generation = models.ForeignKey("integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=64, blank=True)
    is_system = models.BooleanField(null=True)
    free_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    total_value_raw = models.CharField(max_length=32, blank=True, help_text="VSA 'TotalValue'; units undocumented.")

    def __str__(self) -> str:
        return self.name


class SecurityObservation(models.Model):
    """Reported posture attribute (antivirus, firewall, UAC, ransomware). An observation, not a certification."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    observation = models.ForeignKey(AssetObservation, on_delete=models.CASCADE, related_name="security_items")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="+")
    generation = models.ForeignKey("integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="+")
    type = models.CharField(max_length=64, blank=True)
    name = models.CharField(max_length=128, blank=True)
    enabled = models.BooleanField(null=True)
    up_to_date = models.BooleanField(null=True)

    def __str__(self) -> str:
        return f"{self.type}: {self.name}"


# ---------------------------------------------------------------------------------------------- VSA4-01 / VSA4-02


class HealthThresholds(models.Model):
    """Per-customer device-health thresholds. Proposed by a customer admin, approved by a *different* admin.

    Until a row is approved the documented defaults apply (and are labelled as defaults). ``minimum_agent_version``
    blank = agent-version age is *not evaluated* (no baseline is ever assumed).
    """

    class State(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        APPROVED = "approved", "Approved (in effect)"
        SUPERSEDED = "superseded", "Superseded"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="health_thresholds")
    offline_hours = models.PositiveIntegerField(default=24)
    stale_days = models.PositiveIntegerField(default=7)
    disk_warning_free_pct = models.PositiveSmallIntegerField(default=15)
    disk_critical_free_pct = models.PositiveSmallIntegerField(default=5)
    minimum_agent_version = models.CharField(max_length=32, blank=True)
    reason = models.CharField(max_length=500)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PROPOSED)
    proposed_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    reviewed_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["customer"], condition=models.Q(state="approved"), name="inventory_one_approved_thresholds"
            ),
            models.UniqueConstraint(
                fields=["customer"], condition=models.Q(state="proposed"), name="inventory_one_proposed_thresholds"
            ),
            models.CheckConstraint(
                condition=models.Q(disk_critical_free_pct__lt=models.F("disk_warning_free_pct"))
                & models.Q(disk_warning_free_pct__lte=100)
                & models.Q(offline_hours__gte=1)
                & models.Q(stale_days__gte=1),
                name="inventory_thresholds_sane",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.customer_id} thresholds ({self.state})"


class ExpectedSubnet(models.Model):
    """Reviewed expected subnet for a site or group (VSA2-05). Drives *review* observations only, never topology.

    Proposed by a customer admin and approved by a *different* admin; only approved rows are evaluated.
    """

    class ScopeType(models.TextChoices):
        SITE = "site", "Site"
        GROUP = "group", "Group"

    class State(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        RETIRED = "retired", "Retired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="expected_subnets")
    scope_type = models.CharField(max_length=8, choices=ScopeType.choices)
    scope_external_id = models.CharField(max_length=20)
    cidr = models.CharField(max_length=49, help_text="Normalised network (strict), IPv4 or IPv6.")
    reason = models.CharField(max_length=500)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PROPOSED)
    proposed_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    reviewed_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scope_type", "scope_external_id", "cidr"]
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "scope_type", "scope_external_id", "cidr"],
                condition=models.Q(state__in=["proposed", "approved"]),
                name="inventory_expected_subnet_active_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.scope_type}:{self.scope_external_id} {self.cidr}"


# ---------------------------------------------------------------------------------------------- VSA4-03


class DeviceDetailFetch(models.Model):
    """Per device, per generation, per kind: whether a budgeted per-device detail call was made and what it yielded."""

    class Kind(models.TextChoices):
        NOTIFICATIONS = "notifications", "Notifications"
        CUSTOM_FIELDS = "custom_fields", "Custom fields"

    class Status(models.TextChoices):
        COLLECTED = "collected", "Collected"
        NOT_REQUESTED = "not_requested", "Not requested (disabled, outside budget or nothing approved)"
        FAILED = "failed", "Collection failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    observation = models.ForeignKey(AssetObservation, on_delete=models.CASCADE, related_name="detail_fetches")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="+")
    generation = models.ForeignKey("integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NOT_REQUESTED)
    collected_at = models.DateTimeField(null=True, blank=True)
    reported = models.PositiveIntegerField(null=True, blank=True, help_text="Rows returned by the source.")
    stored = models.PositiveIntegerField(null=True, blank=True)
    dropped = models.PositiveIntegerField(
        null=True, blank=True, help_text="Not stored: outside the time window or custom field not allowlisted."
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["observation", "kind"], name="inventory_detailfetch_unique")]
        indexes = [models.Index(fields=["generation", "kind", "status"], name="inventory_detailfetch_gen_idx")]

    def __str__(self) -> str:
        return f"{self.asset_id}:{self.kind}:{self.status}"


class DeviceNotification(models.Model):
    """A VSA X device notification inside the retention window. Message text is PII/secret-redacted before storage."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fetch = models.ForeignKey(DeviceDetailFetch, on_delete=models.CASCADE, related_name="notifications")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="+")
    generation = models.ForeignKey("integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="+")
    vendor_id = models.CharField(max_length=32, blank=True)
    priority = models.CharField(max_length=32, blank=True)
    occurred_at = models.DateTimeField(null=True, blank=True)
    occurred_raw = models.CharField(max_length=40, blank=True)
    message = models.CharField(max_length=1000)
    redactions = models.PositiveSmallIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["customer", "generation", "priority"], name="inventory_notif_cust_gen_idx")]

    def __str__(self) -> str:
        return f"{self.priority}: {self.message[:40]}"


class CustomFieldAllowlist(models.Model):
    """Customer-approved VSA custom field names (VSA-18). Only these are kept; credential-like names are refused.

    Proposed by a customer admin, approved by a *different* admin.
    """

    class State(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        RETIRED = "retired", "Retired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="custom_field_allowlist")
    name = models.CharField(max_length=120)
    name_key = models.CharField(max_length=120, help_text="casefolded name used for matching")
    reason = models.CharField(max_length=500)
    state = models.CharField(max_length=16, choices=State.choices, default=State.PROPOSED)
    proposed_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    reviewed_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "name_key"],
                condition=models.Q(state__in=["proposed", "approved"]),
                name="inventory_customfield_allow_active_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.customer_id}:{self.name} ({self.state})"


class DeviceCustomField(models.Model):
    """An allowlisted custom field value as reported by VSA X (text, max 255)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fetch = models.ForeignKey(DeviceDetailFetch, on_delete=models.CASCADE, related_name="custom_fields")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="+")
    generation = models.ForeignKey("integrations.DatasetGeneration", on_delete=models.PROTECT, related_name="+")
    field_id = models.CharField(max_length=32, blank=True)
    name = models.CharField(max_length=120)
    value = models.CharField(max_length=255, blank=True)
    type = models.CharField(max_length=32, blank=True)

    def __str__(self) -> str:
        return self.name
