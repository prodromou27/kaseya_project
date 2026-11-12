# VSA live tenant validation log

**Status:** no live VSA connection has been performed for this project. This file is intentionally blank beyond the template.

| Date | VSA version/environment | Route/feature | Customer scope (sanitized) | Result | Observed fields | Fixture/test reference | Reviewer |
|---|---|---|---|---|---|---|---|
| TBD | TBD | TBD | TBD | LIVE_VALIDATION_PENDING | TBD | TBD | TBD |
| — | unknown until pilot | `GET /api/v3/assets` (+ include sections) | — | LIVE_VALIDATION_PENDING | docs only | `test_vsa_adapter.py`, `assets_doc_example.json` | — |
| — | unknown until pilot | `GET /api/v3/assets/:id?include=InstalledUpdates` | — | LIVE_VALIDATION_PENDING | docs only | `test_patching.py` | — |
| — | unknown until pilot | `GET /api/v3/organizations`, `/sites`, `/groups`, `/devices` | — | LIVE_VALIDATION_PENDING | docs only | `test_vsa1_hierarchy_network.py` | — |
| — | unknown until pilot | third-party patch status (any source) | — | LIVE_VALIDATION_PENDING; public docs show no route | — | `THIRD_PARTY_PATCH_STATUS` | — |

Store secrets only in approved secret store. Do not paste raw API responses from customer systems into Git.
