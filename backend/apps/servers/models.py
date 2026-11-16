"""SRV-01: server marking and owner groups. Portal-only records: nothing here is read from or written to VSA X.

A device is a server when it is *marked* as one, or - unless it is explicitly marked "not a server" - when its
reported OS name contains "server" (detected). Each server can belong to one owner group, the people responsible for
patching or upgrading it.
"""

from __future__ import annotations

import uuid

from django.db import models


class ServerOwnerGroup(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=120)
    owner_name = models.CharField(max_length=120, blank=True)
    owner_email = models.EmailField(max_length=254, blank=True)
    notes = models.CharField(max_length=1000, blank=True)
    created_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [models.UniqueConstraint(fields=["customer", "name"], name="server_owner_group_unique_name")]

    def __str__(self) -> str:
        return self.name


class ServerDesignation(models.Model):
    """Per-device override. ``is_server`` None = follow detection; True = marked; False = marked "not a server"."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="+")
    asset = models.OneToOneField("inventory.Asset", on_delete=models.CASCADE, related_name="server_designation")
    is_server = models.BooleanField(null=True)
    owner_group = models.ForeignKey(
        ServerOwnerGroup, null=True, blank=True, on_delete=models.SET_NULL, related_name="designations"
    )
    note = models.CharField(max_length=500, blank=True)
    updated_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["customer", "owner_group"], name="server_designation_cust_idx")]

    def __str__(self) -> str:
        return f"{self.asset_id}:{self.is_server}"
