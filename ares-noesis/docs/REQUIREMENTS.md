# Research sheet traceability

| Requirement | Current code | Remaining acceptance gate |
| --- | --- | --- |
| Authentication and project scope | `api/main.py`, `auth.py`, owner checks for projects, jobs and beliefs | PostgreSQL RLS, revocable sessions and finer roles |
| Migration and persistence | `db.py`, `migrate.py`, `models.py`; additive schema upgrade and belief-event guards | Versioned PostgreSQL migrations and backup/restore evidence |
| Lawful ingestion | `connectors/`, `ingestion/`; source adapters retained, offline by default, no default HTTP redirects | Verify each provider's access and quotas, validate live requests, isolate parser, enforce egress policy |
| Hybrid retrieval | `corpus/index.py` uses TF-IDF and LSA with reranking; retraction-set invalidation | Immutable source versions, pgvector/FTS benchmark, retention bounds |
| Evidence and scientific context | `verification/`, `belief/`, `query/` provide heuristic stance and lineage candidates | Exact evidence spans, context compatibility, independent-study labels and calibrated claims |
| Run provenance | `pipeline.py`, `query/pipeline.py` link new reports and hypotheses to jobs | Immutable evidence snapshots and retry-idempotent query persistence |
| Planning and reasoning | `planning/`, `worker.py`, `engines/` | Adaptive evidence budgets and validated tool contracts |
| Hypotheses and learning | `hypothesis/` and append-only belief events | Independent counterevidence, expert review, feedback curation and domain-specific validation |
| Visual workspace | HTML UI polls real API jobs; MCP bridge retained | React, accessible event stream, telemetry-driven 3D |
| Deployment and evaluation | Pinned dependencies, remote development run, gated CI workflow | Verified no-billing hosting, live source tests, scientific benchmarks and final audit |
