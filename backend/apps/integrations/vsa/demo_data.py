"""Deterministic, entirely fictional VSA X tenant for DEMO/fixture mode.

Shapes follow the documented ``/api/v3/assets`` example. All names are fictional; hosts and IDs are synthetic.
Organisation 1001 → DEMO-A (130 assets: exercises >100 paging), 1002 → DEMO-B, 1999 is deliberately unmapped.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

FIXTURE_NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)

# Fictional KB numbers and titles (5099xxx range) — not real Microsoft updates.
_DEMO_UPDATES: list[dict[str, Any]] = [
    {
        "UpdateId": "demo-upd-0001",
        "RevisionNumber": 1,
        "KbArticle": "5099001",
        "Severity": "Critical",
        "Title": "DEMO Cumulative Security Update (KB5099001) (fixture)",
        "Category": "SECURITY_UPDATE_CRITICAL",
        "CvssScore": 9.1,
        "CveCodes": [],
        "ReleaseDate": "2026-10-14",
        "Description": "Fictional",
        "_p": 0.35,
    },
    {
        "UpdateId": "demo-upd-0002",
        "RevisionNumber": 3,
        "KbArticle": "5099002",
        "Severity": "Important",
        "Title": "DEMO Servicing Stack Update (KB5099002) (fixture)",
        "Category": "SECURITY_UPDATE_IMPORTANT",
        "CvssScore": 7.0,
        "CveCodes": [],
        "ReleaseDate": "2026-10-14",
        "Description": "Fictional",
        "_p": 0.5,
    },
    {
        "UpdateId": "demo-upd-0003",
        "RevisionNumber": 1,
        "KbArticle": "5099003",
        "Severity": "Unspecified",
        "Title": "DEMO .NET Quality Rollup (KB5099003) (fixture)",
        "Category": "UPDATE",
        "CvssScore": None,
        "CveCodes": [],
        "ReleaseDate": "2026-09-09",
        "Description": "Fictional",
        "_p": 0.25,
    },
    {
        "UpdateId": "demo-upd-0004",
        "RevisionNumber": 2,
        "KbArticle": "",
        "Severity": "Unspecified",
        "Title": "DEMO Driver Update without KB (fixture)",
        "Category": "DRIVER",
        "CvssScore": None,
        "CveCodes": [],
        "ReleaseDate": "2026-08-01",
        "Description": "Fictional",
        "_p": 0.15,
    },
]

_SOFTWARE_POOL: list[tuple[str, str, list[str]]] = [
    ("Google Chrome", "Google LLC", ["131.0.6778.86", "130.0.6723.117", "131.0.6778.86", "129.0.6668.101"]),
    ("Google Chrome Beta", "Google LLC", ["132.0.6834.15"]),
    ("Mozilla Firefox (x64 en-US)", "Mozilla", ["132.0.2", "131.0.3", "133.0b5"]),
    ("Mozilla Firefox ESR (x64 en-US)", "Mozilla", ["128.4.0", "115.17.0"]),
    ("7-Zip 24.08 (x64)", "Igor Pavlov", ["24.08", "23.01"]),
    ("Adobe Acrobat Reader (64-bit)", "Adobe", ["24.004.20220", "23.008.20470"]),
    ("Notepad++ (64-bit x64)", "Notepad++ Team", ["8.7.1", "8.6.9", "v8.7.1"]),
    ("Contoso Line-of-Business Agent", "Contoso (fictional)", ["4.2", "unknown build"]),
    ("Microsoft Edge", "Microsoft Corporation", ["131.0.2903.70"]),
]


def _asset(rng: random.Random, org_id: int, site_id: int, index: int, prefix: str) -> dict[str, Any]:
    ident = str(uuid.UUID(int=rng.getrandbits(128), version=4))
    name = f"{prefix}-WS{index:03d}" if index % 7 else f"{prefix}-SRV{index:03d}"
    site = "HQ" if index % 3 else "Branch"
    software = []
    for product, publisher, versions in _SOFTWARE_POOL:
        if rng.random() < 0.7:
            software.append({"Name": product, "Publisher": publisher, "Version": rng.choice(versions)})
    asset: dict[str, Any] = {
        "Identifier": ident,
        "Name": name,
        "GroupName": f"{prefix} Org - {site} - {'Servers' if 'SRV' in name else 'Workstations'}",
        "Description": "Windows Server 2022 Standard" if "SRV" in name else "Windows 11 Enterprise",
        "Tags": ["demo"],
        "Type": "mac" if index % 29 == 0 else "windows",
        "ClientVersion": "5.1.2",
        "LastSeenOnline": (FIXTURE_NOW - timedelta(hours=rng.choice([1, 2, 5, 30, 24 * 20]))).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "ComputerId": 50000 + index,
        "OrganizationId": org_id,
        "SiteId": site_id + (0 if index % 3 else 1),
        "AssetInfo": [
            {
                "CategoryName": "System",
                "CategoryData": {
                    "Manufacturer": "Fictional Hardware Co",
                    "Model": "FX-200",
                    "Domain": "demo.invalid",
                    "Owner Name": "should-not-be-stored",
                },
            },
            {"CategoryName": "BIOS", "CategoryData": {"Serial Number": f"DEMO-SN-{org_id}-{index:04d}"}},
            {
                "CategoryName": "Operating System",
                "CategoryData": {
                    "Name": "Windows Server 2022 Standard" if "SRV" in name else "Windows 11 Enterprise",
                    "Version": "10.0.20348.0" if "SRV" in name else "10.0.22631.0",
                    "Product Key": "XXXXX-XXXXX-XXXXX-XXXXX-XXXXX",
                    "Last Logged On User": "DEMO\\should-not-be-stored",
                },
            },
        ],
    }
    if index % 41 != 0:  # every 41st asset omits the section → must surface as "not collected", never "no software"
        asset["InstalledSoftware"] = software
    # Fixture-only private keys (stripped from list responses) drive the derived /sites, /groups and /devices data.
    site_id = asset["SiteId"]
    kind = "Servers" if "SRV" in name else "Workstations"
    asset["_GroupId"] = site_id * 10 + (2 if kind == "Servers" else 1)
    asset["_GroupName"] = kind
    asset["_SiteName"] = site
    asset["_AppliedPolicies"] = _applied_policies(index, kind)
    _add_network_and_hardware(rng, asset, org_id, index)
    if asset["Type"] == "windows" and index % 37 != 0:  # every 37th Windows device omits OS update sections
        available = [u for u in _DEMO_UPDATES if rng.random() < u["_p"]]
        asset["AvailableUpdates"] = [{k: v for k, v in u.items() if k != "_p"} for u in available]
        asset["Updates"] = {
            "Critical": sum(1 for u in available if u["Severity"] == "Critical"),
            "Important": sum(1 for u in available if u["Severity"] == "Important"),
            "Unspecified": sum(1 for u in available if u["Severity"] not in ("Critical", "Important")),
        }
        asset["InstalledUpdates"] = [
            {
                "UpdateId": f"demo-installed-{n}",
                "RevisionNumber": 1,
                "Title": f"DEMO Installed Update {n} (fixture)",
                "Description": "Fictional fixture update",
                "Severity": "Unspecified",
                "ReleaseDate": "2026-10-01",
                "InstalledAt": "2026-10-05T03:00:00",
                "InstalledByAgent": True,
            }
            for n in range(1, 1 + rng.randint(0, 4))
        ]
    return asset


def _add_network_and_hardware(rng: random.Random, asset: dict[str, Any], org_id: int, index: int) -> None:
    """Fictional RFC 1918 / documentation-range addressing. Exercises multi-NIC, IPv6 zones, virtual adapters,
    a deliberate duplicate IP and devices without network/disk/security sections."""
    if index % 23 == 0:
        return  # no network/disk/security sections at all → "not collected"
    third = 10 if asset["SiteId"] % 10 == 1 else 20
    octet = 10 + index if index != 77 else 10 + 76  # index 77 deliberately duplicates index 76's address
    mac = f"0050{org_id % 100:02d}{index // 256:02X}{index % 256:02X}00"
    lan = {
        "Name": "Ethernet",
        "PhysicalAddress": mac,
        "DhcpEnabled": True,
        "Gateways": [f"10.{org_id % 100}.{third}.1"],
        "DnsServers": [f"10.{org_id % 100}.{third}.2"],
        "SubnetMask": "255.255.255.0",
        "IpV4": f"10.{org_id % 100}.{third}.{octet}",
        "IpV6": f"fe80::{index:x}:1%{index % 20 + 1}",
    }
    local = [lan]
    ips = [{"Name": "Ethernet", "MAC": mac, "IPs": [{"IP": lan["IpV4"], "V6": False, "Download": 1, "Upload": 1}]}]
    if index % 9 == 0:  # second, locally-administered (virtual) adapter on another subnet
        vmac = f"0A{org_id % 100:02d}{index:04X}0001"[:12]
        local.append(
            {
                "Name": "vEthernet (Default Switch)",
                "PhysicalAddress": vmac,
                "DhcpEnabled": False,
                "Gateways": [],
                "DnsServers": [],
                "SubnetMask": "255.255.240.0",
                "IpV4": f"172.{16 + org_id % 10}.{index % 16}.{index % 200 + 1}",
                "IpV6": "",
            }
        )
    asset["LocalIpAddresses"] = local
    asset["IpAddresses"] = ips
    asset["PublicIpAddress"] = f"198.51.100.{org_id % 200}"
    asset["Disks"] = [
        {"Name": "C:", "System": True, "FreePercentage": rng.choice([4, 12, 35, 61, 80]), "TotalValue": 256000000}
    ]
    asset["Security"] = [
        {"Type": "Antivirus", "Name": "Fictional AV (fixture)", "Enabled": index % 13 != 0, "UpToDate": index % 7 != 0},
        {"Type": "Firewall", "Name": "Windows Firewall - Domain Profile", "Enabled": True},
    ]


def _applied_policies(index: int, kind: str) -> list[dict[str, Any]]:
    """Deterministic (index-based, no RNG draws) VSA3-04 fixture: shapes copied from the documented example."""
    rows: list[dict[str, Any]] = [
        {"PolicyType": "Antivirus", "PolicyId": None, "PolicyName": "No Antivirus"},
        {
            "PolicyType": "Monitoring",
            "PolicyId": 221,
            "PolicyName": "Free Space (fixture)",
            "Profiles": [{"Id": 1938, "Name": "Free Space Profile", "Category": "Storage", "Settings": {"x": 1}}],
        },
    ]
    if index % 17 == 0:
        return rows  # no Patch Management entry at all -> must surface as "not reported", never "no policy"
    if index % 11 == 0:
        rows.append(
            {"PolicyType": "Patch Management", "PolicyId": None, "PolicyName": "No Policy (Explicitly configured)"}
        )
    elif kind == "Servers" or index % 13 == 0:  # every 13th workstation drifts onto the server policy
        rows.append({"PolicyType": "Patch Management", "PolicyId": 302, "PolicyName": "Servers - monthly (fixture)"})
    else:
        rows.append(
            {"PolicyType": "Patch Management", "PolicyId": 301, "PolicyName": "Workstations - weekly (fixture)"}
        )
    return rows


def _patch_policy(pid: int, name: str, desc: str, severities: list[str]) -> dict[str, Any]:
    return {
        "Id": pid,
        "Name": name,
        "Description": desc,
        "GeneralSettings": {
            "CreateRestorePoint": True,
            "RebootIfRequire": True,
            "NotifyLoggedInUsers": False,
            "Schedule": {
                "Id": -1,
                "Type": {"Id": 1, "Text": "Schedule"},
                "FrequencyInterval": {"Id": 2, "Text": "Weekly"},
            },
            "RebootOption": "DO_NOT_REBOOT",
            "AutomaticUpdate": "AUTO_DOWNLOAD",
            "NotificationSettings": {"Recipients": ["should-not-be-stored@demo.invalid"]},
        },
        "OsRules": [
            {"Field": "SEVERITY", "Operator": "CONTAINS", "Severity": s, "Action": "APPROVE_AND_INSTALL"}
            for s in severities
        ],
        "SoftwareRules": [{"ProductId": "7-zip-x64", "ProductName": "7-Zip (64-bit)", "Action": "INSTALL_AND_UPDATE"}],
    }


@lru_cache(maxsize=1)
def _build() -> dict[str, Any]:
    rng = random.Random(20261112)  # noqa: S311 - deterministic fictional data, not security relevant
    assets = [_asset(rng, 1001, 2001, i, "DEMOA") for i in range(1, 131)]
    assets += [_asset(rng, 1002, 2101, i, "DEMOB") for i in range(1, 13)]
    assets += [_asset(rng, 1999, 2901, i, "UNMAPPED") for i in range(1, 4)]
    organizations = [
        {"Id": 1001, "Name": "Demo Org A (fixture)", "Type": "Customer"},
        {"Id": 1002, "Name": "Demo Org B (fixture)", "Type": "Customer"},
        {"Id": 1999, "Name": "Unmapped Demo Org (fixture)", "Type": "Customer"},
    ]
    patch_policies = {
        "301": _patch_policy(
            301, "Workstations - weekly (fixture)", "Saturday 23:30 (fixture)", ["CRITICAL", "IMPORTANT"]
        ),
        "302": _patch_policy(302, "Servers - monthly (fixture)", "First Sunday (fixture)", ["CRITICAL"]),
    }
    return {"assets": assets, "organizations": organizations, "patch_policies": patch_policies}


def demo_tenant() -> dict[str, Any]:
    import copy

    return copy.deepcopy(_build())
