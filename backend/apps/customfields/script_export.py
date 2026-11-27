"""CFA-12: export a stand-alone Python script that applies a custom field job's writes directly to the VSA X API.

Why this exists: on some tenants a proxy or web application firewall in front of the VSA X API answers the portal's
write with "200 OK" without applying it (see DIAG-01). An administrator whose own workstation is on the firewall's
allowlist can export this script and run it from there, so the authorized write reaches the real API.

Safety rules the generated script keeps (and this module enforces):

* **No secret is ever written into the file.** The API token id and secret are read from the environment at run time
  (``VSA_TOKEN_ID`` / ``VSA_TOKEN_SECRET``); the script refuses to run without them.
* **TLS stays on** (``verify=True``); the script never disables certificate verification.
* **Documented endpoints only** - the same ``assign`` / ``updateAssigned`` routes and body the portal uses.
* **Idempotent and safe to re-run** - each device's current value is read first; a device that already has the target
  value is skipped, and the script reads the value back after writing to confirm it was applied.

It is not a firewall bypass: it runs the authorized call from a machine the firewall already allows.
"""

from __future__ import annotations

import json

from .models import AssignmentItem, AssignmentJob

# Items still needing a write: matched to a device, not already confirmed or skipped as already-correct.
_PENDING_RESULTS = (
    AssignmentItem.Result.FAILED,
    AssignmentItem.Result.VERIFICATION_FAILED,
    AssignmentItem.Result.VERIFICATION_PENDING,
    AssignmentItem.Result.UNKNOWN,
    AssignmentItem.Result.PENDING,
    AssignmentItem.Result.NOT_RUN,
)


def targets(job: AssignmentJob) -> list[dict[str, str]]:
    rows = []
    for item in job.items.filter(match_status=AssignmentItem.Match.MATCHED).order_by("position"):
        # Skip rows already verified / already-correct; include the rest that have a device and a value to set.
        if item.result in (AssignmentItem.Result.VERIFIED, AssignmentItem.Result.ALREADY_CORRECT):
            continue
        value = item.requested_value or job.value
        if not item.device_external_id or value == "":
            continue
        rows.append({"device": item.device_external_id, "hostname": item.hostname, "value": value})
    return rows


def render_script(job: AssignmentJob) -> str:
    """A self-contained Python 3 script (only the ``requests`` library) that applies the job's remaining writes."""
    instance = job.integration_instance
    config = {
        "base_url": instance.base_url.rstrip("/"),
        "field_id": str(job.field.external_id),
        "field_name": job.field.name,
        "routes": list(("customfields", "automation/customfields")),
        "targets": targets(job),
    }
    # json.dumps keeps values safely quoted inside the generated source (no code can be injected through a value).
    config_json = json.dumps(config, indent=2, ensure_ascii=True)
    return _TEMPLATE.replace("__CONFIG__", config_json).replace("__JOB_ID__", str(job.id))


_TEMPLATE = r'''#!/usr/bin/env python3
"""VSA X custom field update - exported by the Odyssey portal for job __JOB_ID__.

Run this from a workstation that is ALLOWED through the proxy / web application firewall in front of the VSA X API,
when the portal reports that VSA X answered OK but did not apply the change.

This script does only what the portal itself does, using the documented VSA X API:
  * reads each device's current value for the field (GET .../customfields/{id}/usage),
  * if it already equals the target value, leaves it alone,
  * otherwise assigns it (POST .../assign) or updates it (PUT .../updateAssigned),
  * reads the value back to confirm it was applied.

The API token is NOT stored in this file and is never fetched from the portal or any server. When you run the script it
asks YOU for the token, right here on your workstation: the token id, then the secret (hidden as you type). Nothing is
saved to disk. Just run it:

    python3 apply_custom_field.py

(If you would rather not be prompted - e.g. to run it unattended - you may instead set VSA_TOKEN_ID and
VSA_TOKEN_SECRET in the environment first; the script uses those when they are present.)

Requires: Python 3.8+ and the "requests" library (pip install requests).
TLS verification is always on. Do not edit this script to turn it off or to route around the firewall; instead run it
from a host the firewall permits, or ask your security team to allowlist the portal's calls.
"""
import getpass
import os
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("This script needs the 'requests' library: pip install requests")

CONFIG = __CONFIG__


def ask_token():
    """Ask for the VSA X API token on this workstation (env vars used when set). Never read from a server or a file."""
    token_id = os.environ.get("VSA_TOKEN_ID", "")
    token_secret = os.environ.get("VSA_TOKEN_SECRET", "")
    try:
        if not token_id:
            token_id = input("VSA X API token id: ").strip()
        if not token_secret:
            token_secret = getpass.getpass("VSA X API token secret (hidden while typing): ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit("\nCancelled - no token entered.")
    if not token_id or not token_secret:
        sys.exit("No API token entered; nothing was sent.")
    return token_id, token_secret


AUTH = ask_token()
HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}
TIMEOUT = 30
BASE = CONFIG["base_url"]
FIELD = CONFIG["field_id"]


def current_value(route, device):
    """Return (assigned, value) for this device, or (None, None) if the field itself was not found on this route."""
    url = "%s/api/v3/%s/%s/usage" % (BASE, route, FIELD)
    flt = "UsageContextType eq 'Device' and ContextItemId eq '%s'" % device
    resp = requests.get(url, params={"$filter": flt}, headers={"Accept": "application/json"},
                        auth=AUTH, timeout=TIMEOUT, verify=True)
    if resp.status_code == 404:
        return None, None
    resp.raise_for_status()
    rows = (resp.json() or {}).get("Data") or []
    for row in rows:
        if str(row.get("ContextItemId")) == str(device):
            return True, str(row.get("Value") if row.get("Value") is not None else "")
    return False, None


def write_value(route, device, value, assigned):
    op = "updateAssigned" if assigned else "assign"
    method = "PUT" if assigned else "POST"
    url = "%s/api/v3/%s/%s/%s" % (BASE, route, FIELD, op)
    body = {"ContextType": "Device", "ContextItemId": device, "UseDefaultValue": False, "Value": value}
    resp = requests.request(method, url, json=body, headers=HEADERS, auth=AUTH, timeout=TIMEOUT, verify=True)
    ctype = resp.headers.get("Content-Type", "")
    documented = False
    try:
        data = (resp.json() or {}).get("Data") or {}
        documented = "ContextItemId" in data
    except ValueError:
        pass
    return resp.status_code, ctype, documented


def find_route(device):
    """Pick the API route (plain or /automation) that knows this field for this device."""
    for route in CONFIG["routes"]:
        assigned, value = current_value(route, device)
        if assigned is not None:
            return route, assigned, value
    return None, None, None


def main():
    targets = CONFIG["targets"]
    print("VSA X: %s" % BASE)
    print("Field %s (%s) - %d device(s)\n" % (FIELD, CONFIG["field_name"], len(targets)))
    ok = skipped = failed = 0
    for t in targets:
        device, value, host = t["device"], t["value"], t.get("hostname") or t["device"]
        try:
            route, assigned, existing = find_route(device)
            if route is None:
                print("  ? %-20s field not found for this device on the API" % host)
                failed += 1
                continue
            if assigned and existing == value:
                print("  = %-20s already '%s'" % (host, value))
                skipped += 1
                continue
            status, ctype, documented = write_value(route, device, value, assigned)
            if status < 200 or status >= 300:
                print("  x %-20s HTTP %s" % (host, status))
                failed += 1
                continue
            time.sleep(2)
            _assigned2, confirmed = current_value(route, device)
            if confirmed == value:
                print("  + %-20s set to '%s'" % (host, value))
                ok += 1
            else:
                hint = ""
                if not documented:
                    detail = ctype or "no content type"
                    hint = (" (answer was %s, not the documented API response"
                            " - a proxy or firewall may still be in the way)" % detail)
                print("  x %-20s VSA X answered OK but the value is still '%s'%s" % (host, confirmed, hint))
                failed += 1
        except requests.RequestException as exc:
            print("  x %-20s %s" % (host, exc))
            failed += 1
    print("\nDone: %d set, %d already correct, %d not applied." % (ok, skipped, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
'''
