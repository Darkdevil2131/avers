# Bounded real-model queue verification — 13 November 2026

This check submits three jobs concurrently as three separate users, then drains them with one separate worker using prepared MiniLM embeddings, a cross-encoder reranker and local Qwen 2.5 1.5B Q4_K_M. It uses a temporary SQLite database and clearly marked synthetic coating observations. It does not call a paid inference service, download models at runtime or provision a host.

## Failed run retained

`inference-queue-failure.json` records the initial failure: one job completed, then a later model process failed. Isolated reproduction of the qa2 fixture returned exit code 1 with `JSONDecodeError: Unterminated string`. The generated response was unfinished JSON. The job pipeline disclosed rejected inference rather than fabricating a successful model response.

The repair bounds schema string lengths and the limitations array. The child now checks the generation finish reason and explicitly rejects token-limit output or invalid JSON instead of crashing while parsing it. Parent validation independently enforces those limits. Empty model answers no longer count as exact source extracts. The original 550-token and 90-second budgets remain unchanged. No partial JSON repair or weakening of citation checks is used.

## Rerun results

| Measurement | Observed result |
| --- | --- |
| Actual model jobs completed | 3/3 |
| Submission to persisted report, including queue time | 22.49 s, 41.92 s, 62.08 s |
| HTTP submission latency | 9.82–14.99 ms |
| Health checks during inference | 119 successful; slowest 74.41 ms |
| Cross-user report access | All 3 denied with HTTP 404 |
| Queued cancellation | Remained cancelled; no report generated |
| API restart | All 3 reports remained available |
| Model hypotheses rejected by critic | 2 contradicted cited direction |
| Backend regression suite | 69 passed; 3 PostgreSQL tests require disposable CI |

Exact output, model hash, rejected candidates and limitations are in `inference-queue-verification.json`. Source IDs refer only to disposable fixtures, not real user documents. The script checkpoints completed jobs and kills its owned process groups during cleanup, including inference children. It always overrides inherited database DSNs with a disposable local database.

Reproduce on an existing authorized no-charge Linux environment after explicit model preparation:

```bash
ARES_MODEL_CACHE=/absolute/path/to/prepared/models \
ARES_REASONER_MODEL=/absolute/path/to/prepared/model.gguf \
PYTHONPATH=. .venv/bin/python scripts/inference_queue_check.py
```

## Boundaries

This is a three-job integration test, not a sustained-load benchmark, a 30-user inference guarantee, a PostgreSQL inference test, or a production SLA. Health latency is not representative of all API endpoints. Identical fixture wording across users exercises isolation and inference plumbing, not general scientific quality. Two contradictory hypotheses were rejected; this does not prove that the critic catches every error. Unvalidated candidates remain unvalidated even when not rejected. Browser/WebGL acceptance, independent scientific evaluation, production database recovery objectives and live zero-cost hosting remain unresolved. No live deployment or billing changes were made.
