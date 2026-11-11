# Bounded API load validation

This is a reproducible staging workload, not a production capacity certification.

`PYTHONPATH=. python scripts/load_check.py` starts a real loopback Uvicorn HTTP server and 30 concurrent authenticated clients against a disposable SQLite database. CI uses a disposable PostgreSQL 16 database with the restricted application role and RLS. The script never targets an arbitrary external URL or uses production credentials by default.

Each client performs ten rounds of an authorized private-source read, a denied cross-project read, and two submissions sharing an idempotency key. It checks private content, expected HTTP statuses, equal run identifiers for duplicate submissions, and ten persisted runs per tenant. Total: 1,200 timed requests, 600 checked read responses and 300 unique queued runs. Setup and final count checks are not included in request latency percentiles.

| Backend / host | Errors | p50 | p95 | p99 | Requests/second |
| --- | ---: | ---: | ---: | ---: | ---: |
| SQLite / hosted development workspace | 0 | 23 ms | 493 ms | 1,663 ms | 223 |
| PostgreSQL 16 / GitHub standard runner | 0 | 170 ms | 245 ms | 270 ms | 165 |

Hosts differ, so this table is not a controlled database performance comparison. Exact measurements and provenance are in load-check.json and postgres-load-check.json. PostgreSQL verification also restores a backup and checks retained reports plus tenant isolation before running the load workload.

The pass condition is correct responses and durable idempotent writes, not a latency SLA. These results exclude local-model inference, web crawling, research queue completion, SSE connection soak, multi-process rate limiting and public-network latency. A short 30-user burst is not evidence of sustained service availability. The target host must be available before deployment-specific capacity and recovery objectives can be measured.

No paid compute, service subscription, card, trial or billable inference endpoint is provisioned by this test. GitHub jobs are restricted to public repositories on standard runners, without artifact or cache storage.
