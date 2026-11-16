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
        # VSA4-01: a few older agents and one unparseable value (deterministic).
        "ClientVersion": "5.0.7" if index % 9 == 0 else ("dev-build" if index == 50 else "5.1.2"),
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
                    "CPU": "Fictional CPU 8-core (fixture)",
                    "Number of Cores": "8",
                    "Number of Logical Processors": "16",
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
    asset["_Notifications"] = _notifications(index, name)
    asset["_CustomFields"] = [
        {
            "Id": 123,
            "Name": "Asset Owner Department",
            "Value": "Finance" if index % 2 else "Engineering",
            "Type": "Text",
        },
        {"Id": 124, "Name": "Local Admin Password", "Value": "should-never-be-stored", "Type": "Text"},
        {"Id": 125, "Name": "Rack", "Value": f"R{index % 4}", "Type": "Text"},
    ]
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
    # VSA4-02 documented always-included aggregates (deterministic, no RNG draws so other fixtures stay stable).
    asset["MemoryTotal"] = 17179869184 if index % 5 else 8589398016
    asset["FirewallEnabled"] = index % 19 != 0
    asset["UacEnabled"] = True
    asset["AntivirusEnabled"] = "enabled" if index % 13 else "disabled"
    asset["AntivirusUpToDate"] = "yes" if index % 7 else "no"


def _notifications(index: int, name: str) -> list[dict[str, Any]]:
    """Deterministic VSA4-03 fixture shaped like the documented example; some messages carry PII to be redacted."""
    if index % 4:
        return []
    rows: list[dict[str, Any]] = [
        {
            "Id": 5000 + index,
            "Message": f"The free space on disk drive C: on the computer '{name}' is below 9% "
            f"({index % 30 + 1}.5 GB free).",
            "DateTime": (FIXTURE_NOW - timedelta(hours=index % 48)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "Priority": "elevated",
        }
    ]
    if index % 12 == 0:
        rows.append(
            {
                "Id": 9000 + index,
                "Message": f"Logon failure for DEMO\\svc-backup{index} reported by admin{index}@demo.invalid",
                "DateTime": int((FIXTURE_NOW - timedelta(hours=2)).timestamp()),  # epoch form, as in the docs example
                "Priority": "critical",
            }
        )
    if index % 40 == 0:
        rows.append({"Id": 1, "Message": "Very old event", "DateTime": "2025-01-01T00:00:00Z", "Priority": "normal"})
    return rows


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
    return {
        "assets": assets,
        "organizations": organizations,
        "patch_policies": patch_policies,
        "automation": _automation(rng, assets),
    }


def _automation(rng: random.Random, assets: list[dict[str, Any]]) -> dict[str, Any]:
    """Synthetic AUT-01 data shaped like the documented automation examples (fixture only, not live)."""
    from datetime import UTC, datetime, timedelta

    workflows = [
        {
            "Id": 501,
            "Name": "DEMO Clean temp files (fixture)",
            "Description": "",
            "IsEnabled": True,
            "TriggerType": "Ad-hoc and Scheduled",
            "TriggerSubType": "Scheduled",
            "UpdatedAt": "2026-10-01T08:00:00Z",
            "ContextType": "Scope",
            "ContextItemId": "71",
            "FolderPath": "DEMO/Maintenance",
        },
        {
            "Id": 502,
            "Name": "DEMO Restart print spooler on alert (fixture)",
            "Description": "",
            "IsEnabled": True,
            "TriggerType": "Notification",
            "TriggerSubType": "SERVICE_STOPPED",
            "UpdatedAt": "2026-10-05T08:00:00Z",
            "ContextType": "Organization",
            "ContextItemId": "1001",
            "FolderPath": "DEMO/Remediation",
        },
        {
            "Id": 503,
            "Name": "DEMO Disabled workflow (fixture)",
            "Description": "",
            "IsEnabled": False,
            "TriggerType": "Ad-hoc and Scheduled",
            "TriggerSubType": "Manual",
            "UpdatedAt": "2026-09-01T08:00:00Z",
            "ContextType": "Device",
            "ContextItemId": "",
            "FolderPath": "DEMO",
        },
    ]
    tasks = [
        {
            "Id": 601,
            "Name": "DEMO Weekly maintenance (fixture)",
            "Description": "",
            "IsEnabled": True,
            "ScopeId": 71,
            "ScopeName": "DEMO All workstations",
            "UpdatedAt": "2026-10-02T08:00:00Z",
            "IsScheduled": True,
            "TotalScripts": 3,
            "IsBuiltIn": False,
            "ContinueOnError": True,
            "ExecutionState": "Idle",
            "FolderPath": "DEMO/Maintenance",
        },
        {
            "Id": 602,
            "Name": "DEMO Inventory refresh (fixture)",
            "Description": "",
            "IsEnabled": False,
            "ScopeId": 72,
            "ScopeName": "DEMO Servers",
            "UpdatedAt": "2026-08-02T08:00:00Z",
            "IsScheduled": False,
            "TotalScripts": 1,
            "IsBuiltIn": False,
            "ContinueOnError": False,
            "ExecutionState": "Idle",
            "FolderPath": "DEMO",
        },
    ]
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    executions, details = [], {}
    demo_a = [a["Identifier"] for a in assets if a["OrganizationId"] == 1001][:40]
    for n, ident in enumerate(demo_a):
        wf = 501 if n % 4 else 502
        failed = n % 7 == 3
        created = now - timedelta(hours=6 * n + 1)
        row = {
            "Id": 9000 + n,
            "WorkflowId": wf,
            "TargetType": "Device",
            "TargetId": ident,
            "TriggerType": "Ad-hoc and Scheduled" if wf == 501 else "Notification",
            "TriggerId": str(wf),
            "Status": "Failed" if failed else "Success",
            "CreatedAt": created.isoformat().replace("+00:00", "Z"),
            "CompletedAt": (created + timedelta(minutes=3)).isoformat().replace("+00:00", "Z"),
            "FolderPath": "DEMO",
        }
        executions.append(row)
        details[str(row["Id"])] = {
            **row,
            "ExecutionSteps": [
                {"WorkflowStepId": 1, "Status": "Success", "Outcome": "Completed", "OutputItems": []},
                {
                    "WorkflowStepId": 2,
                    "Status": "Failed" if failed else "Success",
                    "Outcome": "Script exited with code 1 (fixture)" if failed else "Completed",
                    "OutputItems": [],
                },
            ],
        }
    executions.append(
        {
            "Id": 8999,
            "WorkflowId": 501,
            "TargetType": "Server",
            "TargetId": "",
            "TriggerType": "Ad-hoc and Scheduled",
            "TriggerId": "501",
            "Status": "Success",
            "CreatedAt": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
            "CompletedAt": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
            "FolderPath": "DEMO",
        }
    )
    executions.sort(key=lambda e: e["CreatedAt"], reverse=True)
    script_id = "5c0e0b8e-0000-4000-8000-00000000b17c"
    scripts = [
        {
            "Id": script_id,
            "Name": "DEMO BitLocker status (fixture)",
            "Description": "",
            "CategoryId": 1,
            "CategoryName": "Reporting",
            "Platforms": ["Windows"],
            "CreatedBy": "fixture",
            "IsBuiltIn": False,
            "FolderPath": "DEMO/Reporting",
        },
    ]
    script_runs = {}
    for n, ident in enumerate(demo_a):
        if n % 5 == 4:
            continue  # never ran on this device
        eid = f"00000000-0000-4000-8000-{n:012d}"
        started = (now - timedelta(days=1, hours=n)).isoformat().replace("+00:00", "Z")
        script_runs[f"{script_id}:{ident}"] = {
            "list": [{"Id": eid, "StartTime": started, "DurationInSeconds": 4.2, "State": "Successful"}],
            "details": {
                eid: {
                    "Id": eid,
                    "StartTime": started,
                    "DurationInSeconds": 4.2,
                    "State": "Successful",
                    "Endtime": started,
                    "Output": "free text is never stored (fixture)",
                    "ExitCode": "0",
                    "VariableOutputs": [
                        {
                            "Id": 1,
                            "Name": "BitLockerProtection",
                            "Value": "Off" if n % 6 == 1 else "On",
                            "DataType": "Text",
                        },
                        {"Id": 2, "Name": "RecoveryKey", "Value": "123456-SECRET-FIXTURE", "DataType": "Text"},
                    ],
                }
            },
        }
    return {
        "workflows": workflows,
        "tasks": tasks,
        "executions": executions,
        "execution_details": details,
        "scripts": scripts,
        "script_runs": script_runs,
    }


def demo_tenant() -> dict[str, Any]:
    import copy

    return copy.deepcopy(_build())
