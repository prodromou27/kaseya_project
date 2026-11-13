"""Offline VSA X emulation for fixture instances and contract tests. Never touches the network.

Implements only the documented behaviour the adapter relies on: ``$top`` (capped at 100), ``$skip``,
``$filter=OrganizationId eq <int>``, ``$orderby=Identifier`` and the ``{Data, Meta}`` envelope. Anything else
returns HTTP 400, so an adapter change that depends on undocumented behaviour fails the tests.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

_FILTER = re.compile(r"^OrganizationId eq ([0-9]+)$")
_SITE_FILTER = re.compile(r"^ParentId eq ([0-9]+)$")
_GROUP_FILTER = re.compile(r"^ParentOrganizationId eq ([0-9]+)$")


@dataclass
class FakeResponse:
    status_code: int
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        if isinstance(self.body, Exception):
            raise self.body
        return copy.deepcopy(self.body)


# Documented example of GET /api/v3/ratelimits (abridged), https://api.vsax.net/ 2026-11-13. Fixture only.
DOC_RATE_LIMITS: dict[str, Any] = {
    "Data": {
        "FailedRequestRateLimits": [
            {"Limit": 100, "Remaining": 100, "PeriodInSeconds": 60},
            {"Limit": 2000, "Remaining": 2000, "PeriodInSeconds": 3600},
        ],
        "EndpointRateLimits": [
            {
                "EndpointName": "Get Device Assets",
                "Rules": [
                    {
                        "Limit": 3600,
                        "Remaining": 0,
                        "PeriodInSeconds": 3600,
                        "ResetInSeconds": 3580,
                        "RetryInSeconds": 122,
                    }
                ],
            },
            {
                "EndpointName": "Get All Devices Assets",
                "Rules": [{"Limit": 3600, "Remaining": 3600, "PeriodInSeconds": 3600}],
            },
            {
                "EndpointName": "Get Devices",
                "Rules": [{"Limit": 3600, "Remaining": 3205, "PeriodInSeconds": 3600, "ResetInSeconds": 1903}],
            },
            {
                "EndpointName": "Get Rate Limits",
                "Rules": [{"Limit": 3600, "Remaining": 3599, "PeriodInSeconds": 3600, "ResetInSeconds": 3599}],
            },
        ],
    },
    "Meta": {"ResponseCode": 200},
}


class FixtureVsaTransport:
    def __init__(
        self,
        assets: list[dict[str, Any]],
        organizations: list[dict[str, Any]] | None = None,
        *,
        sites: list[dict[str, Any]] | None = None,
        groups: list[dict[str, Any]] | None = None,
        devices: list[dict[str, Any]] | None = None,
        patch_policies: dict[str, dict[str, Any]] | None = None,
        scripted: list[FakeResponse | Exception] | None = None,
        on_request: Callable[[str, Mapping[str, str]], None] | None = None,
    ):
        self.assets = assets
        self.organizations = organizations or []
        # Hierarchy/device list default to values derived from the assets (fixture-only private keys _GroupId etc.).
        self.sites = sites if sites is not None else _derive_sites(assets)
        self.groups = groups if groups is not None else _derive_groups(assets)
        self.devices = devices if devices is not None else _derive_devices(assets)
        # VSA3-04: per-device applied policies come from the fixture-only "_AppliedPolicies" key; patch policy
        # definitions are keyed by ID. Both are synthetic shapes copied from the documented examples.
        self.patch_policies = patch_policies or {}
        self.scripted = list(scripted or [])  # responses returned (in order) before normal behaviour
        self.on_request = on_request
        self.calls: list[tuple[str, dict[str, str]]] = []

    @classmethod
    def for_instance(cls, instance: Any) -> FixtureVsaTransport:
        from .demo_data import demo_tenant

        tenant = demo_tenant()
        return cls(tenant["assets"], tenant["organizations"], patch_policies=tenant.get("patch_policies"))

    def _list(self, rows: list[dict[str, Any]], skip: int, top: int, total: bool = True) -> FakeResponse:
        meta: dict[str, Any] = {"ResponseCode": 200}
        if total:
            meta["TotalCount"] = len(rows)
        return FakeResponse(200, {"Data": rows[skip : skip + top], "Meta": meta})

    def get(self, url: str, *, params: Mapping[str, str], headers: Mapping[str, str], auth: Any) -> FakeResponse:
        params = dict(params)
        path = re.sub(r"^https://[^/]+", "", url)
        self.calls.append((path, params))
        if self.on_request:
            self.on_request(path, params)
        if self.scripted:
            item = self.scripted.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        detail = re.fullmatch(r"/api/v3/assets/([A-Za-z0-9-]+)", path)
        if detail:
            if params.get("include") != "InstalledUpdates":
                return FakeResponse(400)
            asset = next((a for a in self.assets if str(a.get("Identifier")) == detail.group(1)), None)
            if asset is None:
                return FakeResponse(404)
            data = {k: v for k, v in asset.items() if k in ("Identifier", "Name", "OrganizationId")}
            if "InstalledUpdates" in asset:
                data["InstalledUpdates"] = asset["InstalledUpdates"]
            return FakeResponse(200, {"Data": data, "Meta": {"ResponseCode": 200}})
        if path == "/api/v3/ratelimits":
            return FakeResponse(200, copy.deepcopy(DOC_RATE_LIMITS))
        policy = re.fullmatch(r"/api/v3/patchmanagement/policies/([0-9]+)", path)
        if policy:
            definition = self.patch_policies.get(policy.group(1))
            if definition is None:
                return FakeResponse(404)
            return FakeResponse(200, {"Data": definition, "Meta": {"ResponseCode": 200}})
        try:
            top = int(params.get("$top", "100"))
            skip = int(params.get("$skip", "0"))
        except ValueError:
            return FakeResponse(400)
        if top < 1 or skip < 0:
            return FakeResponse(400)
        detail = re.fullmatch(r"/api/v3/devices/([A-Za-z0-9-]+)/(notifications|customfields)", path)
        if detail:
            dev = next((a for a in self.assets if str(a.get("Identifier")) == detail.group(1)), None)
            if dev is None:
                return FakeResponse(404)
            if detail.group(2) == "notifications":
                if params.get("$orderby") != "DateTime desc":
                    return FakeResponse(400)
                rows = sorted(dev.get("_Notifications", []), key=lambda r: str(r.get("DateTime")), reverse=True)
                return self._list(rows, skip, top)
            return self._list(list(dev.get("_CustomFields", [])), skip, min(top, 100))
        applied = re.fullmatch(r"/api/v3/devices/([A-Za-z0-9-]+)/appliedpolicies", path)
        if applied:
            asset = next((a for a in self.assets if str(a.get("Identifier")) == applied.group(1)), None)
            if asset is None:
                return FakeResponse(404)
            return self._list(list(asset.get("_AppliedPolicies", [])), skip, min(top, 100))
        if path == "/api/v3/devices":
            flt = _FILTER.fullmatch(params.get("$filter", ""))
            if not flt or params.get("$orderby") != "Identifier":
                return FakeResponse(400)
            rows = sorted(
                (d for d in self.devices if str(d.get("OrganizationId")) == flt.group(1)),
                key=lambda d: str(d.get("Identifier", "")),
            )
            return self._list(rows, skip, top, total=params.get("$count") == "true")
        top = min(top, 100)
        if path == "/api/v3/sites":
            flt = _SITE_FILTER.fullmatch(params.get("$filter", ""))
            if not flt:
                return FakeResponse(400)
            return self._list([s for s in self.sites if str(s.get("ParentId")) == flt.group(1)], skip, top)
        if path == "/api/v3/groups":
            flt = _GROUP_FILTER.fullmatch(params.get("$filter", ""))
            if not flt:
                return FakeResponse(400)
            return self._list([g for g in self.groups if str(g.get("ParentOrganizationId")) == flt.group(1)], skip, top)
        if path == "/api/v3/assets":
            rows = self.assets
            flt = params.get("$filter")
            if flt is not None:
                match = _FILTER.fullmatch(flt)
                if not match:
                    return FakeResponse(400)
                rows = [a for a in rows if str(a.get("OrganizationId")) == match.group(1)]
            if params.get("$orderby") not in (None, "Identifier"):
                return FakeResponse(400)
            rows = sorted(rows, key=lambda a: str(a.get("Identifier", "")))
            # InstalledUpdates is documented only on the per-device endpoint; never return it from the list.
            rows = [{k: v for k, v in r.items() if k != "InstalledUpdates" and not k.startswith("_")} for r in rows]
            return FakeResponse(
                200, {"Data": rows[skip : skip + top], "Meta": {"TotalCount": len(rows), "ResponseCode": 200}}
            )
        if path == "/api/v3/organizations":
            rows = self.organizations
            return FakeResponse(
                200, {"Data": rows[skip : skip + top], "Meta": {"TotalCount": len(rows), "ResponseCode": 200}}
            )
        return FakeResponse(404)


def _group_id(asset: dict[str, Any]) -> int:
    return int(asset.get("_GroupId") or (int(asset.get("SiteId") or 0) * 10 + 1))


def _derive_sites(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[int, dict[str, Any]] = {}
    for a in assets:
        if isinstance(a.get("SiteId"), int) and isinstance(a.get("OrganizationId"), int):
            seen.setdefault(
                a["SiteId"],
                {
                    "Id": a["SiteId"],
                    "Name": a.get("_SiteName", f"Site {a['SiteId']}"),
                    "ParentId": a["OrganizationId"],
                    "ParentName": f"Org {a['OrganizationId']}",
                    "ContactInformation": {"Email": "should-not-be-stored@example.invalid"},
                },
            )
    return sorted(seen.values(), key=lambda s: s["Id"])


def _derive_groups(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[int, dict[str, Any]] = {}
    for a in assets:
        if isinstance(a.get("SiteId"), int) and isinstance(a.get("OrganizationId"), int):
            gid = _group_id(a)
            seen.setdefault(
                gid,
                {
                    "Id": gid,
                    "Name": a.get("_GroupName", f"Group {gid}"),
                    "IsActive": True,
                    "ParentSiteId": a["SiteId"],
                    "ParentSiteName": f"Site {a['SiteId']}",
                    "ParentOrganizationId": a["OrganizationId"],
                    "ParentOrganizationName": f"Org {a['OrganizationId']}",
                    "Notes": "free text",
                },
            )
    return sorted(seen.values(), key=lambda g: g["Id"])


def _derive_devices(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for a in assets:
        if not isinstance(a.get("SiteId"), int) or not isinstance(a.get("OrganizationId"), int):
            continue
        out.append(
            {
                "Identifier": a.get("Identifier"),
                "Name": a.get("Name"),
                "GroupId": _group_id(a),
                "GroupName": a.get("_GroupName", f"Group {_group_id(a)}"),
                "IsAgentInstalled": True,
                "IsMdmEnrolled": False,
                "SiteId": a["SiteId"],
                "SiteName": f"Site {a['SiteId']}",
                "OrganizationId": a["OrganizationId"],
                "OrganizationName": f"Org {a['OrganizationId']}",
                "HasCustomFields": False,
            }
        )
    return out
