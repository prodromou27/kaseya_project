# Inventory performance evidence

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
