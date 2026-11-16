"""AUT-01: read-only copy of VSA X automation inventory and workflow results.

Workflows, tasks and executions are tenant-wide in VSA X. An execution is attributed to a customer only through its
target device (``TargetId`` = an asset of that integration); executions without such a device are never shown in a
customer view. Scheduled *task* runs cannot be listed through the documented API, so only the task catalog is kept.
"""

from __future__ import annotations

import uuid

from django.db import models


class AutomationCollection(models.Model):
    """Last collection per integration instance (throttle + status shown to administrators)."""

    integration_instance = models.OneToOneField(
        "integrations.IntegrationInstance", on_delete=models.CASCADE, related_name="automation_collection"
    )
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=24, default="never")  # never|ok|not_permitted|unavailable|failed
    error_code = models.CharField(max_length=64, blank=True)

    def __str__(self) -> str:
        return f"{self.integration_instance_id}:{self.status}"


class AutomationWorkflow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    integration_instance = models.ForeignKey(
        "integrations.IntegrationInstance", on_delete=models.CASCADE, related_name="+"
    )
    external_id = models.CharField(max_length=20)
    name = models.CharField(max_length=255)
    enabled = models.BooleanField(null=True)
    trigger_type = models.CharField(max_length=64, blank=True)
    trigger_subtype = models.CharField(max_length=128, blank=True)
    context_type = models.CharField(max_length=32, blank=True)
    folder_path = models.CharField(max_length=500, blank=True)
    updated_at_raw = models.CharField(max_length=40, blank=True)
    seen_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["integration_instance", "external_id"], name="automation_workflow_unique")
        ]

    def __str__(self) -> str:
        return self.name


class AutomationTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    integration_instance = models.ForeignKey(
        "integrations.IntegrationInstance", on_delete=models.CASCADE, related_name="+"
    )
    external_id = models.CharField(max_length=20)
    name = models.CharField(max_length=255)
    enabled = models.BooleanField(null=True)
    scheduled = models.BooleanField(null=True)
    scope_id = models.CharField(max_length=20, blank=True)
    scope_name = models.CharField(max_length=255, blank=True)
    execution_state = models.CharField(max_length=32, blank=True)
    total_scripts = models.IntegerField(null=True)
    built_in = models.BooleanField(null=True)
    folder_path = models.CharField(max_length=500, blank=True)
    updated_at_raw = models.CharField(max_length=40, blank=True)
    seen_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["integration_instance", "external_id"], name="automation_task_unique")
        ]

    def __str__(self) -> str:
        return self.name


class WorkflowExecution(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    integration_instance = models.ForeignKey(
        "integrations.IntegrationInstance", on_delete=models.CASCADE, related_name="+"
    )
    external_id = models.CharField(max_length=20)
    workflow_external_id = models.CharField(max_length=20)
    target_type = models.CharField(max_length=16, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    # Set only when TargetId is a known asset of this integration; customer follows from that asset.
    asset = models.ForeignKey("inventory.Asset", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    customer = models.ForeignKey(
        "customers.Customer", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    trigger_type = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16)
    created_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    failed_step = models.CharField(
        max_length=300, blank=True, help_text="Outcome of the first failed step (detail call)."
    )
    detail_fetched = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["integration_instance", "external_id"], name="automation_execution_unique")
        ]
        indexes = [models.Index(fields=["customer", "-created_at"], name="automation_exec_cust_idx")]

    def __str__(self) -> str:
        return f"{self.workflow_external_id}:{self.external_id}:{self.status}"


class AutomationScript(models.Model):
    """Script catalog entry (name/category only; script bodies are never requested)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    integration_instance = models.ForeignKey(
        "integrations.IntegrationInstance", on_delete=models.CASCADE, related_name="+"
    )
    external_id = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=255, blank=True)
    platforms = models.JSONField(default=list)
    built_in = models.BooleanField(null=True)
    folder_path = models.CharField(max_length=500, blank=True)
    seen_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["integration_instance", "external_id"], name="automation_script_unique")
        ]

    def __str__(self) -> str:
        return self.name


class ScriptCollector(models.Model):
    """SCR-01: a VSA script whose latest successful run per device is read. Only allowlisted output variables are
    stored (scripts can print anything, including secrets); free-text Output is never stored."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    integration_instance = models.ForeignKey(
        "integrations.IntegrationInstance", on_delete=models.CASCADE, related_name="+"
    )
    script_external_id = models.CharField(max_length=64)
    label = models.CharField(max_length=120)
    allowed_variables = models.JSONField(default=list)
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["integration_instance", "script_external_id"], name="script_collector_unique"
            )
        ]

    def __str__(self) -> str:
        return self.label


class DeviceScriptValue(models.Model):
    class State(models.TextChoices):
        COLLECTED = "collected", "Collected"
        NEVER_RUN = "never_run", "No successful run found"
        FAILED = "failed", "Could not be read"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    collector = models.ForeignKey(ScriptCollector, on_delete=models.CASCADE, related_name="values")
    asset = models.ForeignKey("inventory.Asset", on_delete=models.CASCADE, related_name="+")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="+")
    state = models.CharField(max_length=16, choices=State.choices)
    execution_id = models.CharField(max_length=64, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    values = models.JSONField(default=dict, help_text="{variable: {value, type}} - allowlisted names only.")
    fetched_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["collector", "asset"], name="device_script_value_unique")]
        indexes = [models.Index(fields=["customer", "collector"], name="script_value_cust_idx")]

    def __str__(self) -> str:
        return f"{self.collector_id}:{self.asset_id}:{self.state}"


class PatchGlobalRules(models.Model):
    """GR-01: tenant-wide patch global rules (configuration, applies to every device; never deployment state)."""

    integration_instance = models.OneToOneField(
        "integrations.IntegrationInstance", on_delete=models.CASCADE, related_name="patch_global_rules"
    )
    os_rules = models.JSONField(default=list)
    software_rules = models.JSONField(default=list)
    fetched_at = models.DateTimeField()

    def __str__(self) -> str:
        return f"global rules {self.integration_instance_id}"


class AutomationScope(models.Model):
    """GR-01: automation scope with its matching criteria, device count and the tasks/workflows using it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    integration_instance = models.ForeignKey(
        "integrations.IntegrationInstance", on_delete=models.CASCADE, related_name="+"
    )
    external_id = models.CharField(max_length=20)
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=500, blank=True)
    criteria = models.JSONField(default=list, help_text="[{type, identifier}] (custom-field values are not kept)")
    total_devices = models.IntegerField(null=True)
    used_by = models.JSONField(default=list, help_text="[{type: Task|Workflow, id}]")
    seen_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["integration_instance", "external_id"], name="automation_scope_unique")
        ]

    def __str__(self) -> str:
        return self.name
