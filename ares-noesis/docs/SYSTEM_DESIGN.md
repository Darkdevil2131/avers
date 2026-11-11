> Archive documentation. See ENGINEERING_PROGRESS.md for the current verified state.

# Noesis system design

Format follows the system-design checklist: requirements, high-level design, deep dives, scale and reliability, trade-offs, what to revisit.
Numbers marked **measured** come from `scripts/bench_index.py` and the test suite in the build sandbox (synthetic text, 1 CPU, no network).
Numbers marked **estimate** are arithmetic from stated assumptions, not measurements.

## 1. Requirements
**Functional.** (a) Ask a research question and get a graded-evidence report. (b) Upload a paper and get claims, statistics checks, evidence, beliefs,
hypotheses, experiment proposals. (c) Harvest and search a literature corpus. (d) Human feedback on beliefs, fully audited. (e) Standalone exact engines
(statistics, math, dimensions, simulation). (f) Agent access via MCP.

**Non-functional.**
| Property | Target | Status |
|---|---|---|
| Honesty | no fabricated evidence; every claim traceable to page/section or paper+DOI; LLM output must quote its source | enforced in code, tested |
| Multi-user safety | users cannot see each other's projects/jobs/beliefs | enforced, tested (404 not 403) |
| Durability | accepted jobs survive restarts/crashes | DB queue with leases, tested (crash + reclaim) |
| Latency | query/analyse are async jobs; reads < 100 ms | search p50 **measured** 23 ms at 10k docs |
| Cost | CPU-only, free APIs, LLM optional with per-document call cap (default 30) | yes |
| Scale (stated assumption) | 50 users, ~1,000 jobs/day, corpus up to ~100k papers on one node | see section 4 |

**Out of scope / constraints.** Sandbox could not reach any external API, so all connectors are unverified live. No GPU. Not a clinical decision tool.

## 2. High-level design
```
 Browser UI ─┐                         ┌─ MCP server (noesis_mcp, 24 tools) ── any MCP client
 REST clients┴─► FastAPI (auth, rate limit, metrics) ◄─┘
                    │ enqueue (jobs table)          reads: SQL
                    ▼                                  ▲
              PostgreSQL / SQLite ◄── Worker(s) ──────┘   Worker = pipeline: parse → claims → plan(DAG) → engines
                    ▲                    │                       → agents/connectors → evidence grading → beliefs
                    │                    ├─► Connectors (OpenAlex, PubMed, arXiv, …) ─► corpus_papers
             S3/MinIO (originals)        └─► LLM API (optional, grounded)               ─► graph (NetworkX, built per run)
```
Data flow for a question: `POST /projects/{id}/query` → job row (queued) → worker claims it → understand → seed hypotheses →
retrieve (local corpus index first, live APIs second) → stance + grade → beliefs → graph → gap hypotheses → critic (LLM, optional) →
experiment proposals → veracity gate → report → job result.

**API surface** (all `/api/v1`, JSON): projects, documents (upload/analyze), query, jobs, claims, beliefs (+history, feedback, restore),
hypotheses, graph, report, papers, corpus (stats/search/sync/runs), engines (+run), connectors, auth (register/login), `/metrics`, `/health`.

## 3. Deep dives
**Data model.** `projects(owner_id)`, `documents(sha256 unique per project)`, `claims(page, section, kind, meta)`, `corpus_papers(content_hash unique)`
(global, deduplicated, license + retraction + design + sample size), `external_papers` (per-project copies for isolation), `beliefs`/`evidence_items`/`belief_events`
(append-only history with snapshots), `hypotheses`, `jobs(payload, attempts, lease_until, worker_id)`, `users`, `audit_log`, `reports`.
Schema changes are forward-only via `migrate.ensure_schema` (adds tables/columns); renames/drops need hand-written migrations.

**Job queue.** Rows in `jobs`. Claim = SELECT candidate, then compare-and-set UPDATE (rowcount must be 1), so two workers cannot both win, on any database.
Postgres adds `FOR UPDATE SKIP LOCKED`. A running job holds a lease (default 15 min); an expired lease makes it claimable again; after `max_attempts` it is failed
with a reason. SQLite lock errors are retried with jitter. Each pipeline task runs in a SAVEPOINT so one task's DB error cannot poison the rest.
*Known gap:* no lease heartbeat, so a legitimately >15-minute job would be re-claimed (raise `NOESIS_LEASE_SECONDS`).

**Retrieval.** TF-IDF (uni+bigrams, min_df=2, 200k feature cap, float32) blended 0.6/0.4 with LSA (≈1 component per 12 docs, cap 100), optional dense embeddings.
Retracted papers are excluded and flipping the flag invalidates the cached index. Blend weights and LSA size are untuned; tune with `noesis eval`.

**Belief engine.** Log-odds pooling with prior odds 1; each independence group (default: first-author surname) contributes at most its strongest item; self-reported
evidence contributes nothing; likelihood-ratio table (1.2/1.8/3/5 by grade) is an assumption. Output is flagged `calibrated:false`. Chosen over a full Bayesian network
because the dependency structure between papers is not observable from metadata alone.

**LLM grounding.** The model may only return claims/stances with a verbatim quote that is verified against the source string in code; ungrounded output is dropped
or downgraded to neutral. Source text is delimited as data. Per-document call budget bounds cost.

## 4. Scale and reliability
**Measured (synthetic text, sandbox):**
| Corpus | Index build | Query p50 / p95 | Peak RSS |
|---|---|---|---|
| 2,000 | 1.8 s | 4 / 6 ms | 274 MB |
| 10,000 | 7.7 s | 23 / 25 ms | 552 MB |
| 30,000 | 17.7 s | 53 / 61 ms | 916 MB |
Before the min_df/feature-cap fix: 10,000 docs took 35.6 s, 2.1 GB, 280 ms/query, and 30,000 docs was killed by the OOM killer.
Ingest ≈ 900 papers/s (SQLite, no network). **Estimate:** build time and memory scale roughly linearly, so 100k docs ≈ 1 minute and ≈ 3 GB.
That is the in-process ceiling (`index_max_docs`, default 100k, most recent indexed). Beyond it, move retrieval to pgvector/OpenSearch behind `CorpusIndex.search`.

**Known scaling limits (honest list).**
- The index rebuilds in-process whenever the corpus changes; queries during a rebuild wait. Harvest in batches; consider background rebuild.
- Rate limiter, metrics counters and index cache are per-process. With >1 API replica, limits multiply by replica count; use a gateway/Redis limiter.
- SQLite is single-writer: a long analysis holds the write lock. Use PostgreSQL for concurrent users (compose file provided).
- The evidence graph is rebuilt per run from SQL (fine at project scale); a project-spanning graph needs Neo4j or a materialised table.
- Jobs are pulled by polling (2 s). Fine at ~1k jobs/day (**estimate**: ~0.01 jobs/s average); revisit at ≥100 jobs/s.

**Failure modes covered by tests:** connector 503/429/timeouts (retry with backoff, then structured "unavailable"), LLM outage (rule fallback, errors recorded), worker crash
(lease expiry), double analyse (409 with existing job id), oversized/corrupt/page-bomb uploads, retracted papers, DB error in one task (savepoint), parallel workers
(no double-claim, stressed 15×), login brute force (429), account enumeration timing.

**Observability.** `/metrics` (Prometheus): requests by route/status + latency sums, jobs by status, corpus and belief counts. Suggested alerts: `noesis_jobs{status="queued"}` growing,
5xx rate, any job `failed` with "gave up".

## 5. Trade-off log
| Decision | Chosen | Alternative | Why / cost |
|---|---|---|---|
| Queue | Postgres/SQLite table | Celery+Redis, Kafka | zero extra infra, durable; polling latency, DB load at high rate |
| Graph | NetworkX over SQL | Neo4j | no extra service; per-run rebuild, no cross-project traversal |
| Retrieval | TF-IDF+LSA | dense embeddings/vector DB | CPU-only, offline; weaker semantics, memory ceiling ~100k docs |
| Belief math | log-odds pooling, independence groups | Bayesian network, Dempster-Shafer | auditable and cheap; assumed LR table, crude independence proxy |
| Stance | LLM with quote check, lexical fallback | fine-tuned NLI model | no training data/GPU; quality unmeasured until `noesis eval` is run |
| Hypotheses | graph structure + critic | free LLM generation | traceable to sources; generic on small corpora |
| Auth | scrypt + HMAC tokens, per-project owner | OIDC | stdlib only; no SSO/reset flow |
| Engines | exact (SciPy/SymPy), refuse unsupported physics | LLM answers | verifiable; narrow coverage |

## 6. What to revisit as it grows
1. Run `noesis eval scifact` and tune retrieval/stance on real numbers (nothing else matters until quality is measured).
2. Move retrieval to a vector store before ~100k docs; add background index rebuild.
3. Lease heartbeat; Redis-backed shared rate limiting; Alembic once the schema has destructive changes.
4. OIDC, audit export, per-user LLM quotas.
5. React frontend, Neo4j, simulators (OpenFOAM/SPICE) as separate worker pools.
