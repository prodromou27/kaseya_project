from __future__ import annotations

import uuid

from django.db import models


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
