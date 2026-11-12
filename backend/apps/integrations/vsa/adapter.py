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
ASSET_INCLUDE = "Tags,AssetInfo,InstalledSoftware,Updates,AvailableUpdates"
DETAIL_INCLUDE = "InstalledUpdates"

ALLOWED_PATHS = [
    re.compile(r"/api/v3/assets"),
    re.compile(r"/api/v3/assets/[A-Za-z0-9-]{1,64}"),
    re.compile(r"/api/v3/organizations"),
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
