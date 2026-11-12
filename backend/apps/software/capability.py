"""Third-party patch status capability (VSA3-07).

Evidence (2026-11-13): the public VSA X API v3 reference (https://api.vsax.net/) documents 72 routes; none returns
per-device third-party patch applicability or deployment/pending/failed/reboot state. Patch policy ``SoftwareRules``
are configuration only. Until a supported source is verified on the installed VSA version (LIVE_VALIDATION_PENDING),
the status is reported as UNAVAILABLE and nothing is inferred from installed-version comparisons.
"""

THIRD_PARTY_PATCH_STATUS = {
    "state": "UNAVAILABLE",
    "message": (
        "Pending third-party patch status is not available from the configured VSA API; installed version comparison "
        "is shown separately."
    ),
    "evidence": "Public VSA X API v3 reference reviewed 2026-11-13: no device-level third-party patch status route.",
    "live_validation": "LIVE_VALIDATION_PENDING",
}
