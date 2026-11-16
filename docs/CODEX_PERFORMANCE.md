# Inventory performance evidence

## P5-06 - representative related data (2026-11-16)

Same workstation and PostgreSQL 16.2. `benchmark_inventory --rows 100000 --related` generates, for one customer, **100,000 devices** (10% servers by OS name) and per device 15 installed programs, OS update rows (0-6 available + 2 installed, 40-update pool), patch status and applied patch policy (4% "No Policy"): **2,299,995 observation rows**. Seeding took 791 s. Synthetic fixture only; no vendor calls, no catalog/compliance evaluation or lifecycle entries (see limits).

```powershell
.venv/Scripts/python.exe manage.py benchmark_inventory --rows 100000 --related --confirm-fixture-only
.venv/Scripts/python.exe manage.py benchmark_inventory --measure-existing --confirm-fixture-only   # add --skip-reports for API paths only
```

Single process, warm database, after `ANALYZE`. "Before" was measured straight after the bulk load (statistics not yet gathered), so paths whose code did not change (inventory list, search, OS updates list) also got faster and **no improvement is claimed for them**. The changed paths were confirmed with cProfile on the same data (ORM objects built per call, below).

| Path | Before | After | Queries |
|---|---:|---:|---:|
| Servers list (10,000 servers) | 49.6 s | **1.9 s** | 11 |
| Servers, needing attention | 47.5 s | **2.1 s** | 11 |
| Servers, all devices (`scope=all`, 100k) | 74.5 s | **~10.7 s** (rows) | 11 |
| Patch-policy summary | 39.5 s | **4.0 s** | 13 |
| Monthly scorecard (rows) | 140.9 s | **13.9 s** | 65 |
| Device health summary | 5.6 s | 3.0 s | 9 |
| OS updates summary | 3.4 s | 3.2 s | 16 |
| Inventory page of 50 / hostname search | 2.1 / 2.0 s | 0.32 / 0.26 s | 4 |
| Report: asset inventory CSV, 100k rows (20 MB) | 25.6 s | 12.2 s | 14 |
| Report: asset inventory XLSX, 100k rows (5 MB) | 71.5 s | 36.3 s | 14 |
| Report: patch-policy coverage CSV, 100k rows | 33.1 s | 15.2 s | 16 |
| Report: server patching by owner CSV, 10k rows | 25.9 s | **2.5 s** | 28 |
| Report: customer scorecard PDF | 141.0 s | **14.4 s** | 84 |

Changes (behaviour-preserving; existing tests plus a new equivalence test):

- **Servers** (`servers/status.py`): candidate servers are pre-filtered in the database (OS name contains "server", or marked), only the needed columns are loaded, and the OS-lifecycle check runs for those devices only instead of every device (`lifecycle.os_rows(asset_ids=...)`). Profile: 500,000 ORM objects → 20,000.
- **Patch-policy rows** (`patching/policy_queries.py`): plain value rows instead of full device/source/snapshot objects. Profile 26.5 s → 9.6 s under cProfile.
- **Third-party exposure** (`software/thirdparty.py`): program-name normalisation is cached and rule coverage memoised per (policy, program); the scorecard uses `outdated_totals()`, which evaluates only installations the catalog marked outdated and is regression-tested to equal the full evaluation's outdated totals. This was 67 s of the 141 s scorecard.

Server-owner PDF with 10,000 servers is refused by the existing PDF row guard (`too_many_rows_for_pdf`); per-owner PDFs or CSV/XLSX are the route for very large estates.

**Proposed SLOs (for owner approval, not yet approved):** interactive pages at 100k devices ≤ 5 s (all list/summary pages above meet it except `Servers → all devices` ~11 s and the scorecard ~14 s, which is also produced as a background report); background reports of 100k rows ≤ 60 s (all meet it).

Limits of this evidence: one customer, single process, no concurrency, no RSS/CPU measurement, no vendor synchronization throughput (the rate budget is per integration and covered by sync tests, not measured live), no catalog compliance results or lifecycle entries (so software-outdated and lifecycle classification costs are understated), workstation not the target host. P5-06 stays open until the SLOs are approved and measured on the target environment.

## CX-08 - inventory only (2026-11-14)

2026-11-14, local Windows development workstation, PostgreSQL 16.2, Python 3.12.10, Node 24.22.2. Generated synthetic normalized inventory, **100,000 devices**, one customer and one fixture source. No vendor calls or real customer data. These are single-process observations, not production SLAs, vendor synchronization timings or a concurrency test.

## Reproduction

Create an empty PostgreSQL database named `bench_*`, set the ordinary POSTGRES_* environment variables to it, then:

```powershell
.venv/Scripts/python.exe manage.py migrate --noinput
.venv/Scripts/python.exe manage.py benchmark_inventory --rows 100000 --confirm-fixture-only
# Subsequent read-only measurements of the same generated fixture:
.venv/Scripts/python.exe manage.py benchmark_inventory --measure-existing --confirm-fixture-only
```

The command refuses production, a database without the `bench_` prefix, missing explicit fixture acknowledgement, or pre-existing customer/user/integration data. Re-measurement verifies the generated fixture identity. It stages the synthetic generation and publishes it after all batches are inserted; it does not exercise the vendor connector. The benchmark account has an unusable password. No database is dropped or reset.

## Observed results

| Path | Before | After | Queries | Result population |
|---|---:|---:|---:|---:|
| Inventory page of 50 | 0.2708 s | 0.3014 s | 4 | 100,000 total |
| Exact hostname substring search | 0.2404 s | 0.2608 s | 4 | 1 |
| Offline filter, page of 50 | 0.1965 s | 0.2111 s | 4 | 76,200 |
| Customer health summary | 16.3327 s | **1.2915 s** | 9 | 100,000 |

The health-summary change avoids creating full ORM devices/related objects and detailed hardware dictionaries just to aggregate counts. It streams scalar observation fields, pins the generation set once, loads compact disk/security/policy facts and applies the same classification functions used by detailed investigations. Every health dimension is regression-checked against the detailed population. No cache or speculative index was added; the measured summary improvement is about **12.6×**. Other timings show ordinary run variation, not an asserted improvement.

## Practical limits

- Generated workload has no installed-software, disk or security-observation rows. Related-observation memory use, millions of software installations and cross-customer concurrency are not benchmarked.
- No RSS/CPU saturation, concurrent sync/report throughput or host/container benchmark is claimed.
- The detailed health device-list/report paths still materialize detailed classifications; this optimization targets the dashboard summary.
- The initial fixture seed was retried after supplying required `collected_at`; that failed transaction rolled back. The first measurement then needed an explicit loopback Host header; the generated fixture was retained and measured without reseeding.
- VSA4-06 remains partial until representative related-data/concurrency/synchronization load is measured in the approved target environment.
