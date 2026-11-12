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
        "Type": "windows",
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
    return asset


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
    return {"assets": assets, "organizations": organizations}


def demo_tenant() -> dict[str, Any]:
    import copy

    return copy.deepcopy(_build())
