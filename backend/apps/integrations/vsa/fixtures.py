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


# VSA5-EXEC fixture state: (integration id, device id) -> (group id, group name). In-process only (demo/tests); a
# fixture move is visible to later fixture reads of the same integration so read-back and the next sync agree.
FIXTURE_MOVES: dict[tuple[str, str], tuple[str, str]] = {}
# CFA fixture state: (integration id, field id, device id) -> device-level value written through the portal.
FIXTURE_CUSTOM_FIELDS: dict[tuple[str, str, str], str] = {}
_USAGE_FILTER = re.compile(r"UsageContextType eq 'Device'(?: and ContextItemId eq '([A-Za-z0-9-]{1,64})')?")
_ID_FILTER = re.compile(r"Id eq ([0-9]{1,18})")


def _definitions(automation: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list(automation.get("custom_field_definitions", []))


def _public(definition: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in definition.items() if not k.startswith("_")}


def device_level_fields(instance_id: str, asset: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Field id -> {Id, Name, Value, Type} assigned on the device itself (fixture data + portal writes)."""
    rows = {str(r.get("Id")): dict(r) for r in asset.get("_CustomFields", [])}
    for (iid, fid, did), value in FIXTURE_CUSTOM_FIELDS.items():
        if iid == instance_id and did == str(asset.get("Identifier")):
            rows.setdefault(fid, {"Id": int(fid), "Name": "", "Type": "Text"})["Value"] = value
    return rows


class FixtureCustomFieldWriteTransport:
    """Answers the documented assign/updateAssigned calls for a fixture integration. Never touches the network."""

    def __init__(self, instance: Any, status: int | None = None, read: Any = None):
        self.instance_id = str(instance.id)
        self.status = status
        self.read = read or FixtureVsaTransport.for_instance(instance)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def send(self, method: str, url: str, *, json: Mapping[str, Any], headers: Mapping[str, str], auth: Any) -> Any:
        path = re.sub(r"^https://[^/]+", "", url)
        self.calls.append((method, path, dict(json)))
        if self.status is not None:
            return FakeResponse(self.status)
        match = re.fullmatch(r"/api/v3/(?:automation/)?customfields/([0-9]+)/(assign|updateAssigned)", path)
        if not match or (method, match.group(2)) not in (("POST", "assign"), ("PUT", "updateAssigned")):
            return FakeResponse(404)
        fid, device = match.group(1), str(json.get("ContextItemId"))
        definition = next((d for d in _definitions(self.read.automation) if str(d["Id"]) == fid), None)
        asset = next((a for a in self.read.assets if str(a.get("Identifier")) == device), None)
        if definition is None or asset is None or json.get("ContextType") != "Device":
            return FakeResponse(400)
        exists = fid in device_level_fields(self.instance_id, asset)
        if exists != (match.group(2) == "updateAssigned"):
            return FakeResponse(400)  # documented: assign on an existing / update on a missing assignment
        FIXTURE_CUSTOM_FIELDS[(self.instance_id, fid, device)] = str(json.get("Value"))
        data = {"ContextType": "Device", "ContextItemId": device, "Id": int(fid), "Name": definition["Name"]}
        return FakeResponse(200, {"Data": {**data, "Value": str(json.get("Value")), "Type": definition["Type"]}})


class FixtureWriteTransport:
    """Answers the single move PUT for a fixture integration. Never touches the network."""

    def __init__(self, instance: Any, status: int = 200):
        self.instance_id = str(instance.id)
        self.status = status
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def put(self, url: str, *, json: Mapping[str, Any], headers: Mapping[str, str], auth: Any) -> FakeResponse:
        path = re.sub(r"^https://[^/]+", "", url)
        self.calls.append((path, dict(json)))
        match = re.fullmatch(r"/api/v3/devices/([A-Za-z0-9-]+)/move", path)
        if not match or self.status >= 300:
            return FakeResponse(self.status if match else 404)
        group = str(json.get("GroupId"))
        FIXTURE_MOVES[(self.instance_id, match.group(1))] = (group, f"Group {group}")
        return FakeResponse(
            200, {"Data": {"DeviceIdentifier": match.group(1), "GroupId": int(group), "GroupName": f"Group {group}"}}
        )


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
        automation: dict[str, Any] | None = None,
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
        # AUT-01: tenant-wide workflows/tasks/executions (synthetic, documented shapes); empty unless provided.
        self.automation = automation or {}
        self.instance_id = ""
        self.calls: list[tuple[str, dict[str, str]]] = []

    @classmethod
    def for_instance(cls, instance: Any) -> FixtureVsaTransport:
        from .demo_data import demo_tenant

        tenant = demo_tenant()
        transport = cls(
            tenant["assets"],
            tenant["organizations"],
            patch_policies=tenant.get("patch_policies"),
            automation=tenant.get("automation"),
        )
        transport.instance_id = str(instance.id)
        moved = {d: g for (i, d), g in FIXTURE_MOVES.items() if i == str(instance.id)}
        for device in transport.devices:
            if str(device.get("Identifier")) in moved:
                gid, gname = moved[str(device["Identifier"])]
                device["GroupId"], device["GroupName"] = (
                    int(gid),
                    next((str(g.get("Name")) for g in transport.groups if str(g.get("Id")) == gid), gname),
                )
        return transport

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
        run = re.fullmatch(
            r"/api/v3/automation/scripts/([A-Za-z0-9-]+)/device/([A-Za-z0-9-]+)/executions(?:/([A-Za-z0-9-]+))?", path
        )
        if run:
            runs = self.automation.get("script_runs", {}).get(f"{run.group(1)}:{run.group(2)}")
            if runs is None:
                return self._list([], skip, min(top, 100))
            if run.group(3):
                found = runs["details"].get(run.group(3))
                return FakeResponse(200, {"Data": found, "Meta": {"ResponseCode": 200}}) if found else FakeResponse(404)
            if params.get("$orderby") != "StartTime desc":
                return FakeResponse(400)
            rows = list(runs["list"])
            if params.get("$filter") == "State eq 'Successful'":
                rows = [r for r in rows if r.get("State") == "Successful"]
            return self._list(rows, skip, min(top, 100))
        scoped = re.fullmatch(r"/api/v3/(organizations|sites|groups)/([0-9]+)/customfields", path)
        if scoped:
            rows = self.automation.get("scope_custom_fields", {}).get(f"{scoped.group(1)}:{scoped.group(2)}", [])
            return self._list(list(rows), skip, min(top, 100))
        if path == "/api/v3/patchmanagement/globalrules":
            rules = self.automation.get("global_rules")
            return FakeResponse(200, {"Data": rules, "Meta": {"ResponseCode": 200}}) if rules else FakeResponse(404)
        scope = re.fullmatch(r"/api/v3/scopes/([0-9]+)(/usage)?", path)
        if scope:
            found = next((x for x in self.automation.get("scopes", []) if str(x["Id"]) == scope.group(1)), None)
            if found is None:
                return FakeResponse(404)
            if scope.group(2):
                return self._list(
                    list(self.automation.get("scope_usage", {}).get(scope.group(1), [])), skip, min(top, 100)
                )
            return FakeResponse(200, {"Data": found, "Meta": {"ResponseCode": 200}})
        if path == "/api/v3/scopes":
            rows = [
                {k: v for k, v in x.items() if k in ("Id", "Name", "Description", "UpdatedAt")}
                for x in self.automation.get("scopes", [])
            ]
            return self._list(rows, skip, min(top, 100))
        if path == "/api/v3/automation/scripts":
            return self._list(list(self.automation.get("scripts", [])), skip, min(top, 100))
        execution = re.fullmatch(r"/api/v3/automation/workflows/executions/([0-9]+)", path)
        if execution:
            found = self.automation.get("execution_details", {}).get(execution.group(1))
            return FakeResponse(200, {"Data": found, "Meta": {"ResponseCode": 200}}) if found else FakeResponse(404)
        if path in (
            "/api/v3/automation/workflows",
            "/api/v3/automation/tasks",
            "/api/v3/automation/workflows/executions",
        ):
            key = {"/api/v3/automation/workflows": "workflows", "/api/v3/automation/tasks": "tasks"}.get(
                path, "executions"
            )
            if key == "executions" and params.get("$orderby") != "CreatedAt desc":
                return FakeResponse(400)
            return self._list(list(self.automation.get(key, [])), skip, min(top, 100))
        if path == "/api/v3/customFields":
            return self._list([_public(d) for d in _definitions(self.automation)], skip, min(top, 100))
        usage = re.fullmatch(r"/api/v3/customfields/([0-9]+)/usage", path)
        if usage:
            flt = _USAGE_FILTER.fullmatch(params.get("$filter", ""))
            if not flt:
                return FakeResponse(400)
            rows = [
                {"UsageContextType": "Device", "ContextItemId": str(a["Identifier"]), "Value": f["Value"]}
                for a in self.assets
                for fid, f in device_level_fields(self.instance_id, a).items()
                if fid == usage.group(1) and (flt.group(1) is None or flt.group(1) == str(a["Identifier"]))
            ]
            return self._list(rows, skip, min(top, 100))
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
            fields = device_level_fields(self.instance_id, dev)
            for d in _definitions(self.automation):  # inherited organisation values (fixture-only "_OrgValue")
                if d.get("_OrgValue") is not None and str(d["Id"]) not in fields:
                    fields[str(d["Id"])] = {
                        "Id": d["Id"],
                        "Name": d["Name"],
                        "Value": d["_OrgValue"],
                        "Type": d["Type"],
                    }
            for fid, row in fields.items():
                row["Name"] = row.get("Name") or next(
                    (d["Name"] for d in _definitions(self.automation) if str(d["Id"]) == fid), ""
                )
            rows = list(fields.values())
            only = _ID_FILTER.fullmatch(params.get("$filter", ""))
            if only:
                rows = [r for r in rows if str(r.get("Id")) == only.group(1)]
            return self._list(rows, skip, min(top, 100))
        one = re.fullmatch(r"/api/v3/devices/([A-Za-z0-9-]+)", path)
        if one:
            device = next((d for d in self.devices if str(d.get("Identifier")) == one.group(1)), None)
            return FakeResponse(200, {"Data": device, "Meta": {"ResponseCode": 200}}) if device else FakeResponse(404)
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
