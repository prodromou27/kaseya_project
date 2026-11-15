"""Third-party patch exposure (read model).

VSA X exposes no per-device third-party patch deployment state (see capability THIRD_PARTY_PATCH_STATUS). What the
portal *can* state from collected evidence, per installed program on each device:

* version state - from the reviewed catalog comparison (current / outdated / newer / unknown / not catalogued /
  excluded);
* patch-rule coverage - whether the device's assigned VSA Patch Management policy (configuration, collected via
  ``appliedpolicies`` + ``patchmanagement/policies/{id}``) contains a SoftwareRule for that program, matched by
  normalised name.

"Outdated and not covered by any rule" is the actionable gap. "Covered" means configuration only - whether VSA
deployed the update is not available from the API and is never implied.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from apps.inventory.queries import current_generations

DISCLAIMER = (
    "Patch-rule coverage is VSA policy configuration. Whether VSA X actually deployed an update is not available "
    "from the VSA X API, so it is never shown as done."
)
_PAREN = re.compile(r"\([^)]*\)")
_VERSIONISH = re.compile(r"\bv?\d+(?:\.\d+)+\b")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")

COVERAGE = ("covered", "not_covered", "no_policy", "unknown")


def normalise(name: str) -> str:
    """'7-Zip 24.08 (x64)' and '7-Zip (64-bit)' -> '7 zip'."""
    text = _PAREN.sub(" ", name.casefold())
    text = _VERSIONISH.sub(" ", text)
    return " ".join(_NON_ALNUM.sub(" ", text).split())


def _rule_matches(rule_norm: str, install_norm: str) -> bool:
    if not rule_norm or not install_norm:
        return False
    return (
        rule_norm == install_norm or f" {rule_norm} " in f" {install_norm} " or f" {install_norm} " in f" {rule_norm} "
    )


def _device_policies(
    customer_id: Any, gens: list[Any]
) -> tuple[dict[str, tuple[str, str]], dict[tuple[Any, str], dict]]:
    """asset_id -> (patch_state, policy_id); (generation_id, policy_id) -> definition summary."""
    from apps.patching.models import AppliedPolicyObservation, PatchPolicyDefinition

    devices = {
        str(a): (state, pid)
        for a, state, pid in AppliedPolicyObservation.objects.filter(
            customer_id=customer_id, generation__in=gens
        ).values_list("asset_id", "patch_state", "patch_policy_id")
    }
    definitions = {}
    for gid, pid, status, name, rules in PatchPolicyDefinition.objects.filter(
        customer_id=customer_id, generation__in=gens
    ).values_list("generation_id", "policy_id", "status", "name", "software_rules"):
        parsed = [
            (normalise(str(r.get("ProductName") or r.get("ProductId") or "")), str(r.get("Action") or ""))
            for r in (rules or [])
            if isinstance(r, dict)
        ]
        definitions[(gid, pid)] = {"status": status, "name": name, "rules": parsed}
    return devices, definitions


def rows(customer_id: Any) -> list[dict[str, Any]]:
    """One row per installed program per device in the current snapshot."""
    from apps.software.models import ComplianceResult, SoftwareInstallation

    gens = list(current_generations(customer_id))
    devices, definitions = _device_policies(customer_id, gens)
    state_by_install = {
        inst: (state, product, ref)
        for inst, state, product, ref in ComplianceResult.objects.filter(
            customer_id=customer_id, evaluation__is_current=True, evaluation__generation__in=gens
        ).values_list("installation_id", "state", "product__product", "catalog_revision__reference_version")
    }
    from apps.inventory.queries import current_observations

    hosts = {
        str(a): (h, gid, gname)
        for a, h, gid, gname in current_observations(customer_id).values_list(
            "asset_id", "hostname", "group_external_id", "group_name"
        )
    }
    out = []
    for inst_id, asset_id, gen_id, name, publisher, version in (
        SoftwareInstallation.objects.filter(customer_id=customer_id, generation__in=gens)
        .values_list("id", "asset_id", "generation_id", "raw_name", "raw_publisher", "raw_version")
        .iterator()
    ):
        aid = str(asset_id)
        state, product, reference = state_by_install.get(inst_id, ("unsupported", None, None))
        patch_state, policy_id = devices.get(aid, ("unknown", ""))
        norm = normalise(name)
        coverage, action, policy_name = "unknown", "", ""
        if patch_state in ("explicit_none", "not_reported"):
            coverage = "no_policy"
        elif patch_state == "assigned" and policy_id:
            definition = definitions.get((gen_id, policy_id))
            if definition and definition["status"] == "collected":
                policy_name = definition["name"]
                match = next((a for r, a in definition["rules"] if _rule_matches(r, norm)), None)
                coverage, action = ("covered", match) if match is not None else ("not_covered", "")
        host, gid, gname = hosts.get(aid, ("", "", ""))
        out.append(
            {
                "asset_id": aid,
                "hostname": host,
                "group_external_id": gid,
                "group_name": gname,
                "program": name,
                "publisher": publisher,
                "program_key": norm or name.casefold(),
                "installed_version": version,
                "catalog_product": product,
                "reference_version": reference,
                "version_state": state,
                "coverage": coverage,
                "rule_action": action,
                "policy_name": policy_name,
            }
        )
    return out


def summary(customer_id: Any, search: str = "", only_outdated: bool = False) -> dict[str, Any]:
    data = rows(customer_id)
    programs: dict[str, dict[str, Any]] = {}
    totals = {
        "installs": 0,
        "outdated": 0,
        "outdated_covered": 0,
        "outdated_not_covered": 0,
        "outdated_no_policy": 0,
        "outdated_unknown": 0,
    }
    for r in data:
        p = programs.setdefault(
            r["program_key"],
            {
                "program_key": r["program_key"],
                "program": r["program"],
                "publisher": r["publisher"],
                "catalog_product": r["catalog_product"],
                "reference_version": r["reference_version"],
                "devices": set(),
                "installs": 0,
                "outdated": 0,
                "versions": defaultdict(int),
                "coverage": dict.fromkeys(COVERAGE, 0),
                "outdated_coverage": dict.fromkeys(COVERAGE, 0),
                "actions": set(),
            },
        )
        p["devices"].add(r["asset_id"])
        p["installs"] += 1
        p["versions"][r["installed_version"]] += 1
        p["coverage"][r["coverage"]] += 1
        p["catalog_product"] = p["catalog_product"] or r["catalog_product"]
        p["reference_version"] = p["reference_version"] or r["reference_version"]
        if r["rule_action"]:
            p["actions"].add(r["rule_action"])
        totals["installs"] += 1
        if r["version_state"] == "outdated":
            p["outdated"] += 1
            p["outdated_coverage"][r["coverage"]] += 1
            totals["outdated"] += 1
            key = {
                "covered": "outdated_covered",
                "not_covered": "outdated_not_covered",
                "no_policy": "outdated_no_policy",
            }
            totals[key.get(r["coverage"], "outdated_unknown")] += 1
    result = []
    needle = search.casefold().strip()
    for p in programs.values():
        if needle and needle not in p["program"].casefold() and needle not in (p["publisher"] or "").casefold():
            continue
        if only_outdated and not p["outdated"]:
            continue
        versions = sorted(p["versions"].items(), key=lambda kv: -kv[1])
        result.append(
            {
                **{
                    k: p[k]
                    for k in (
                        "program_key",
                        "program",
                        "publisher",
                        "catalog_product",
                        "reference_version",
                        "installs",
                        "outdated",
                        "coverage",
                        "outdated_coverage",
                    )
                },
                "devices": len(p["devices"]),
                "rule_actions": sorted(p["actions"]),
                "versions": [{"version": v, "installs": n} for v, n in versions[:5]],
                "version_count": len(versions),
            }
        )
    # Actionable first: outdated and not covered, then outdated, then most installed.
    result.sort(
        key=lambda p: (
            -p["outdated_coverage"]["not_covered"] - p["outdated_coverage"]["no_policy"],
            -p["outdated"],
            -p["installs"],
            p["program"].casefold(),
        )
    )
    return {"totals": totals, "programs": result, "disclaimer": DISCLAIMER}


def filter_rows(data: list[dict[str, Any]], params: Any) -> list[dict[str, Any]]:
    program = params.get("program", "")
    coverage = params.get("coverage", "")
    state = params.get("version_state", "")
    search = str(params.get("search", ""))[:100].casefold().strip()
    out = data
    if program:
        out = [r for r in out if r["program_key"] == program]
    if coverage in COVERAGE:
        out = [r for r in out if r["coverage"] == coverage]
    if state:
        out = [r for r in out if r["version_state"] == state]
    if search:
        out = [r for r in out if search in r["hostname"].casefold() or search in r["program"].casefold()]
    return sorted(out, key=lambda r: (r["hostname"].casefold(), r["program"].casefold()))
