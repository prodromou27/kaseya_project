"""Kaseya VSA X read-only adapter (docs-verified 2026-11-12, see ``capabilities.json``)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from ..http import ReadOnlyHttpClient, Transport
from ..models import IntegrationInstance
from ..secrets import resolve_basic
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
            credential = resolve_basic(instance.credential_ref)
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

    def get_installed_updates(self, identifier: str) -> Any:
        """``GET /api/v3/assets/:id?include=InstalledUpdates`` → raw body. Identifier is validated before use."""
        if not _DEVICE_ID.fullmatch(identifier or ""):
            raise ValueError("Unsafe device identifier.")
        return self.client.get_json(f"/api/v3/assets/{identifier}", {"include": DETAIL_INCLUDE}).json

    def _paged(self, path: str, params: dict[str, str], page_size: int, max_pages: int = 2000) -> Iterator[Page]:
        skip = 0
        for _ in range(max_pages):
            result = self.client.get_json(path, {**params, "$top": str(page_size), "$skip": str(skip)})
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
