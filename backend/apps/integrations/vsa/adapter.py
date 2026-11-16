"""Kaseya VSA X read-only adapter (docs-verified 2026-11-12, see ``capabilities.json``)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from ..http import ReadOnlyHttpClient, Transport
from ..models import IntegrationInstance
from ..secrets import resolve_instance_basic
from .schema import Page, PageInvalid, RecordInvalid, VsaOrganization, normalize_organization, parse_page

PAGE_SIZE = 100  # documented maximum for $top
MAX_PAGES = 5000  # hard stop: 500k assets per organisation
# Sections collected from the list endpoint. InstalledUpdates is only available per device (budgeted).
ASSET_INCLUDE = "Tags,AssetInfo,InstalledSoftware,Updates,AvailableUpdates,IpAddresses,LocalIpAddresses,Disks,Security"
DEVICE_PAGE_SIZE = 500  # documented max is 2147483647; bounded for memory
DETAIL_INCLUDE = "InstalledUpdates"

ALLOWED_PATHS = [
    re.compile(r"/api/v3/assets"),
    re.compile(r"/api/v3/assets/[A-Za-z0-9-]{1,64}"),
    re.compile(r"/api/v3/organizations"),
    re.compile(r"/api/v3/sites"),
    re.compile(r"/api/v3/groups"),
    re.compile(r"/api/v3/devices"),
    # VSA3-04 (docs-verified 2026-11-13): per-device applied policies and patch policy configuration. GET only.
    re.compile(r"/api/v3/devices/[A-Za-z0-9-]{1,64}/appliedpolicies"),
    # VSA5-EXEC read-back (docs-verified 2026-11-13): one device, to confirm a move. GET only.
    re.compile(r"/api/v3/devices/[A-Za-z0-9-]{1,64}"),
    re.compile(r"/api/v3/patchmanagement/policies/[0-9]{1,18}"),
    # VSA1-01 connection test (docs-verified 2026-11-13): read-only rate-limit status for the token.
    re.compile(r"/api/v3/ratelimits"),
    # VSA4-03 (docs-verified 2026-11-13): per-device notifications and custom fields. The tenant-wide
    # /api/v3/notifications route is deliberately NOT allowed: it cannot be filtered by organisation.
    re.compile(r"/api/v3/devices/[A-Za-z0-9-]{1,64}/notifications"),
    re.compile(r"/api/v3/devices/[A-Za-z0-9-]{1,64}/customfields"),
    # AUT-01 (docs-verified 2026-11-16, https://api.vsax.net/): read-only automation inventory and workflow results.
    # The run/cancel routes are POST and stay off the allowlist (the client has no write method anyway).
    re.compile(r"/api/v3/automation/workflows"),
    re.compile(r"/api/v3/automation/workflows/executions"),
    re.compile(r"/api/v3/automation/workflows/executions/[0-9]{1,18}"),
    re.compile(r"/api/v3/automation/tasks"),
    # SCR-01 (docs-verified 2026-11-16): script catalog and per-device script results (VariableOutputs).
    re.compile(r"/api/v3/automation/scripts"),
    # GR-01 (docs-verified 2026-11-16): patch global rules and automation scopes.
    re.compile(r"/api/v3/patchmanagement/globalrules"),
    re.compile(r"/api/v3/scopes"),
    re.compile(r"/api/v3/scopes/[0-9]{1,18}"),
    re.compile(r"/api/v3/scopes/[0-9]{1,18}/usage"),
    # CF-02 (docs-verified 2026-11-16): organisation/site/group custom field values.
    re.compile(r"/api/v3/(organizations|sites|groups)/[0-9]{1,18}/customfields"),
    re.compile(r"/api/v3/automation/scripts/[A-Za-z0-9-]{1,64}/device/[A-Za-z0-9-]{1,64}/executions"),
    re.compile(
        r"/api/v3/automation/scripts/[A-Za-z0-9-]{1,64}/device/[A-Za-z0-9-]{1,64}/executions/[A-Za-z0-9-]{1,64}"
    ),
]
_DEVICE_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")

_ORG_ID = re.compile(r"^[0-9]{1,18}$")


def validate_org_id(external_org_id: str) -> int:
    """VSA X OrganizationId is a documented integer. Reject anything else (prevents OData injection)."""
    if not _ORG_ID.fullmatch(external_org_id or ""):
        raise ValueError("VSA X organization IDs are integers.")
    return int(external_org_id)


@dataclass
class AssetPage:
    skip: int
    records: list[dict[str, Any]]
    total_count: int | None
    request_count: int


# Per-device detail calls: one retry on timeout/5xx. A device VSA X fails on deterministically (observed live:
# GetSystemAppliedPolicies -> 500 "The given key was not present in the dictionary") is marked failed quickly
# instead of being retried with backoff. Asset paging keeps the client default.
DETAIL_RETRIES = 1


class VsaXAdapter:
    provider = "vsa_x"

    def __init__(self, instance: IntegrationInstance, transport: Transport | None = None, **client_kwargs: Any):
        if instance.provider != IntegrationInstance.Provider.VSA_X:
            raise ValueError("Not a VSA X integration instance.")
        self.instance = instance
        if instance.is_fixture:
            from .fixtures import FixtureVsaTransport

            transport = transport or FixtureVsaTransport.for_instance(instance)
            auth = None
        else:
            credential = resolve_instance_basic(instance)
            auth = (credential.username, credential.password)
        self.client = ReadOnlyHttpClient(
            base_url=instance.base_url,
            provider=self.provider,
            allowed_paths=ALLOWED_PATHS,
            auth=auth,
            max_rps=float(instance.max_rps),
            transport=transport,
            is_fixture=instance.is_fixture,
            **client_kwargs,
        )

    def iter_asset_pages(self, organization_id: str, start_skip: int = 0) -> Iterator[AssetPage]:
        """Pages of raw asset dicts for ONE approved organisation, in stable ``Identifier`` order."""
        org = validate_org_id(organization_id)
        skip = start_skip
        for _ in range(MAX_PAGES):
            result = self.client.get_json(
                "/api/v3/assets",
                {
                    "$top": str(PAGE_SIZE),
                    "$skip": str(skip),
                    "$filter": f"OrganizationId eq {org}",
                    "$orderby": "Identifier",
                    "include": ASSET_INCLUDE,
                },
            )
            page: Page = parse_page(result.json)
            yield AssetPage(
                skip=skip, records=page.records, total_count=page.total_count, request_count=self.client.request_count
            )
            if len(page.records) < PAGE_SIZE:
                return
            skip += len(page.records)
        raise PageInvalid("Page limit exceeded; refusing to paginate further.")

    def sample_assets(self, organization_id: str, top: int = 5) -> Page:
        """One small page with exactly the sync's ``include`` sections, for the read-only probe command."""
        org = validate_org_id(organization_id)
        result = self.client.get_json(
            "/api/v3/assets",
            {
                "$top": str(max(1, min(top, 20))),
                "$skip": "0",
                "$filter": f"OrganizationId eq {org}",
                "$orderby": "Identifier",
                "include": ASSET_INCLUDE,
            },
        )
        return parse_page(result.json)

    def get_installed_updates(self, identifier: str) -> Any:
        """``GET /api/v3/assets/:id?include=InstalledUpdates`` → raw body. Identifier is validated before use."""
        if not _DEVICE_ID.fullmatch(identifier or ""):
            raise ValueError("Unsafe device identifier.")
        return self.client.get_json(
            f"/api/v3/assets/{identifier}", {"include": DETAIL_INCLUDE}, max_retries=DETAIL_RETRIES
        ).json

    def get_applied_policies(self, identifier: str) -> list[dict[str, Any]]:
        """``GET /api/v3/devices/:id/appliedpolicies`` (documented ``$top`` max 100) → raw policy dicts."""
        if not _DEVICE_ID.fullmatch(identifier or ""):
            raise ValueError("Unsafe device identifier.")
        rows: list[dict[str, Any]] = []
        for page in self._paged(
            f"/api/v3/devices/{identifier}/appliedpolicies", {}, 100, max_pages=5, max_retries=DETAIL_RETRIES
        ):
            rows.extend(page.records)
        return rows

    def get_notifications(self, identifier: str, top: int) -> list[dict[str, Any]]:
        """Most recent ``top`` device notifications (``$orderby=DateTime desc``). The time window is applied by the
        caller: the OData date-literal syntax for ``$filter`` on DateTime is not documented."""
        if not _DEVICE_ID.fullmatch(identifier or ""):
            raise ValueError("Unsafe device identifier.")
        result = self.client.get_json(
            f"/api/v3/devices/{identifier}/notifications",
            {"$orderby": "DateTime desc", "$top": str(max(1, min(top, 500))), "$skip": "0"},
            max_retries=DETAIL_RETRIES,
        )
        return parse_page(result.json).records

    def get_custom_fields(self, identifier: str) -> list[dict[str, Any]]:
        """``GET /api/v3/devices/:id/customfields`` (``$top`` max 100). Callers keep only allowlisted names."""
        if not _DEVICE_ID.fullmatch(identifier or ""):
            raise ValueError("Unsafe device identifier.")
        rows: list[dict[str, Any]] = []
        for page in self._paged(
            f"/api/v3/devices/{identifier}/customfields", {}, 100, max_pages=10, max_retries=DETAIL_RETRIES
        ):
            rows.extend(page.records)
        return rows

    # ------------------------------------------------------------------------------------------ automation (AUT-01)

    def list_workflows(self) -> list[dict[str, Any]]:
        """``GET /api/v3/automation/workflows`` - tenant-wide workflow definitions (names, trigger, enabled)."""
        rows: list[dict[str, Any]] = []
        for page in self._paged("/api/v3/automation/workflows", {}, 100, max_pages=50):
            rows.extend(page.records)
        return rows

    def list_tasks(self) -> list[dict[str, Any]]:
        """``GET /api/v3/automation/tasks`` - tenant-wide tasks (enabled, scheduled, scope, state)."""
        rows: list[dict[str, Any]] = []
        for page in self._paged("/api/v3/automation/tasks", {}, 100, max_pages=50):
            rows.extend(page.records)
        return rows

    def iter_workflow_executions(self, max_pages: int = 20) -> Iterator[list[dict[str, Any]]]:
        """``GET /api/v3/automation/workflows/executions`` newest first; the caller stops at its time window."""
        for page in self._paged(
            "/api/v3/automation/workflows/executions", {"$orderby": "CreatedAt desc"}, 100, max_pages=max_pages
        ):
            yield page.records

    def get_workflow_execution(self, execution_id: str) -> Any:
        """``GET /api/v3/automation/workflows/executions/:id`` - one execution with its step outcomes."""
        if not re.fullmatch(r"[0-9]{1,18}", execution_id or ""):
            raise ValueError("Unsafe execution identifier.")
        return self.client.get_json(
            f"/api/v3/automation/workflows/executions/{execution_id}", {}, max_retries=DETAIL_RETRIES
        ).json

    def list_scope_custom_fields(self, scope: str, scope_id: str) -> list[dict[str, Any]]:
        """``GET /api/v3/{organizations|sites|groups}/:id/customfields`` -> [{Id, Name, Value, Type}]."""
        if scope not in ("organizations", "sites", "groups") or not _ORG_ID.fullmatch(scope_id or ""):
            raise ValueError("Unsafe scope.")
        rows: list[dict[str, Any]] = []
        for page in self._paged(
            f"/api/v3/{scope}/{scope_id}/customfields", {}, 100, max_pages=10, max_retries=DETAIL_RETRIES
        ):
            rows.extend(page.records)
        return rows

    def get_device_group(self, device_id: str) -> tuple[str, str]:
        """``GET /api/v3/devices/{id}`` -> (GroupId, GroupName), used only to read back a group move."""
        if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", device_id or ""):
            raise ValueError("Unsafe device identifier.")
        data = (self.client.get_json(f"/api/v3/devices/{device_id}", {}, max_retries=DETAIL_RETRIES).json or {}).get(
            "Data"
        ) or {}
        return str(data.get("GroupId") or "")[:20], str(data.get("GroupName") or "")[:255]

    def get_global_rules(self) -> Any:
        """``GET /api/v3/patchmanagement/globalrules`` -> {Data: {OsRules: [], SoftwareRules: []}} (configuration)."""
        return self.client.get_json("/api/v3/patchmanagement/globalrules", {}, max_retries=DETAIL_RETRIES).json

    def list_scopes(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in self._paged("/api/v3/scopes", {}, 100, max_pages=10):
            rows.extend(page.records)
        return rows

    def get_scope(self, scope_id: str) -> Any:
        if not _ORG_ID.fullmatch(scope_id or ""):
            raise ValueError("Unsafe scope identifier.")
        return self.client.get_json(f"/api/v3/scopes/{scope_id}", {}, max_retries=DETAIL_RETRIES).json

    def get_scope_usage(self, scope_id: str) -> list[dict[str, Any]]:
        if not _ORG_ID.fullmatch(scope_id or ""):
            raise ValueError("Unsafe scope identifier.")
        rows: list[dict[str, Any]] = []
        for page in self._paged(f"/api/v3/scopes/{scope_id}/usage", {}, 100, max_pages=5, max_retries=DETAIL_RETRIES):
            rows.extend(page.records)
        return rows

    def list_scripts(self) -> list[dict[str, Any]]:
        """``GET /api/v3/automation/scripts`` - tenant-wide script catalog (names only; bodies are not requested)."""
        rows: list[dict[str, Any]] = []
        for page in self._paged("/api/v3/automation/scripts", {}, 100, max_pages=50):
            rows.extend(page.records)
        return rows

    def latest_script_run(self, script_id: str, device_id: str) -> dict[str, Any] | None:
        """Newest *successful* execution of a script on a device, or None. Documented filter/sort on State/StartTime."""
        if not _DEVICE_ID.fullmatch(script_id or "") or not _DEVICE_ID.fullmatch(device_id or ""):
            raise ValueError("Unsafe identifier.")
        result = self.client.get_json(
            f"/api/v3/automation/scripts/{script_id}/device/{device_id}/executions",
            {"$orderby": "StartTime desc", "$filter": "State eq 'Successful'", "$top": "1", "$skip": "0"},
            max_retries=DETAIL_RETRIES,
        )
        records = parse_page(result.json).records
        return records[0] if records else None

    def get_script_run(self, script_id: str, device_id: str, execution_id: str) -> Any:
        """``GET .../executions/:executionId`` - includes ExitCode and VariableOutputs (Output is never stored)."""
        for value in (script_id, device_id, execution_id):
            if not _DEVICE_ID.fullmatch(value or ""):
                raise ValueError("Unsafe identifier.")
        return self.client.get_json(
            f"/api/v3/automation/scripts/{script_id}/device/{device_id}/executions/{execution_id}",
            {},
            max_retries=DETAIL_RETRIES,
        ).json

    def get_rate_limits(self) -> Any:
        """``GET /api/v3/ratelimits`` -> raw body. Used only by the administrator connection test."""
        return self.client.get_json("/api/v3/ratelimits", {}).json

    def get_patch_policy(self, policy_id: str) -> Any:
        """``GET /api/v3/patchmanagement/policies/:id`` → raw body (policy *configuration*, not deployment state)."""
        if not _ORG_ID.fullmatch(policy_id or ""):
            raise ValueError("Unsafe policy identifier.")
        return self.client.get_json(
            f"/api/v3/patchmanagement/policies/{policy_id}", {}, max_retries=DETAIL_RETRIES
        ).json

    def _paged(
        self,
        path: str,
        params: dict[str, str],
        page_size: int,
        max_pages: int = 2000,
        max_retries: int | None = None,
    ) -> Iterator[Page]:
        skip = 0
        for _ in range(max_pages):
            result = self.client.get_json(
                path, {**params, "$top": str(page_size), "$skip": str(skip)}, max_retries=max_retries
            )
            page = parse_page(result.json)
            yield page
            if len(page.records) < page_size:
                return
            skip += len(page.records)
        raise PageInvalid("Page limit exceeded.")

    def iter_sites(self, organization_id: str) -> Iterator[Page]:
        org = validate_org_id(organization_id)
        return self._paged("/api/v3/sites", {"$filter": f"ParentId eq {org}", "$orderby": "Id"}, PAGE_SIZE)

    def iter_groups(self, organization_id: str) -> Iterator[Page]:
        org = validate_org_id(organization_id)
        return self._paged("/api/v3/groups", {"$filter": f"ParentOrganizationId eq {org}", "$orderby": "Id"}, PAGE_SIZE)

    def iter_devices(self, organization_id: str) -> Iterator[Page]:
        org = validate_org_id(organization_id)
        return self._paged(
            "/api/v3/devices",
            {"$filter": f"OrganizationId eq {org}", "$orderby": "Identifier", "$count": "true"},
            DEVICE_PAGE_SIZE,
        )

    def list_organizations(self) -> tuple[list[VsaOrganization], list[str]]:
        """All organisations visible to the token. Returns (organisations, invalid-record reasons)."""
        orgs: list[VsaOrganization] = []
        invalid: list[str] = []
        skip = 0
        for _ in range(200):
            result = self.client.get_json("/api/v3/organizations", {"$top": str(PAGE_SIZE), "$skip": str(skip)})
            page = parse_page(result.json)
            for item in page.records:
                try:
                    orgs.append(normalize_organization(item))
                except RecordInvalid as exc:
                    invalid.append(exc.reason)
            if len(page.records) < PAGE_SIZE:
                return orgs, invalid
            skip += len(page.records)
        raise PageInvalid("Organisation page limit exceeded.")
