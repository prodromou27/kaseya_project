# VSA live tenant validation log

**Status:** first live observations recorded 2026-11-23 (group move write). Everything else remains LIVE_VALIDATION_PENDING.

| Date | VSA version/environment | Route/feature | Customer scope (sanitized) | Result | Observed fields | Fixture/test reference | Reviewer |
|---|---|---|---|---|---|---|---|
| TBD | TBD | TBD | TBD | LIVE_VALIDATION_PENDING | TBD | TBD | TBD |
| 2026-11-23 | production tenant (version not recorded) | `PUT /api/v3/devices/{id}/move` | one customer, 5 devices | FAILED: HTTP 200 for each, response body **not** the documented JSON, and read-back shows the device still in its source group (move not applied). `GET /api/v3/devices/{id}` read-back works and returns `Data.GroupId`/`GroupName` as documented. Cause under investigation (token permission or a proxy answering PUT) | status code only (body never stored) | `test_group_move_execution.py::test_200_without_json_body_*` | product owner (reported), OPS-07 |
| — | unknown until pilot | `GET /api/v3/assets` (+ include sections) | — | LIVE_VALIDATION_PENDING | docs only | `test_vsa_adapter.py`, `assets_doc_example.json` | — |
| — | unknown until pilot | `GET /api/v3/assets/:id?include=InstalledUpdates` | — | LIVE_VALIDATION_PENDING | docs only | `test_patching.py` | — |
| — | unknown until pilot | `GET /api/v3/organizations`, `/sites`, `/groups`, `/devices` | — | LIVE_VALIDATION_PENDING | docs only | `test_vsa1_hierarchy_network.py` | — |
| — | unknown until pilot | `GET /api/v3/devices/:id/appliedpolicies`, `GET /api/v3/patchmanagement/policies/:id` | — | LIVE_VALIDATION_PENDING | docs only | `test_patch_policies.py` | — |
| — | unknown until pilot | `GET /api/v3/ratelimits` (connection test) | — | LIVE_VALIDATION_PENDING | docs only | `test_connection_test.py` | — |
| — | unknown until pilot | third-party patch status (any source) | — | LIVE_VALIDATION_PENDING; public docs show no route | — | `THIRD_PARTY_PATCH_STATUS` | — |

Store secrets only in approved secret store. Do not paste raw API responses from customer systems into Git.
