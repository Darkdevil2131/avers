> Archive documentation. See ENGINEERING_PROGRESS.md for the current verified state.

# Plan coverage: the two PDFs vs. what exists (checked against the code, not the intent)
Legend: BUILT = implemented and unit/integration tested | UNVERIFIED-LIVE = real code, never run against the real service (sandbox has no network) | NOT BUILT

## Flow (both PDFs)
| PDF item | Status |
|---|---|
| Query Understanding (type, concepts, constraints, time) | BUILT (LLM when key set, rules otherwise; LLM path UNVERIFIED-LIVE) |
| Domain Router | BUILT (keyword lexicon; medicine, technology, space, chemistry, physics, earth science, life science, social science, mathematics, plus a broad `general` fallback). Crude vocabulary matching, no classifier; only the first three have domain-specific connectors/design rules |
| Exec Summary: query -> hypotheses -> search per hypothesis | BUILT (`POST /projects/{id}/query`) |
| Research Planner as task DAG | BUILT for document mode (failure isolation, replanning). Query mode: engines are routed by question type (`query/engine_route.py`) with per-engine status, but the sequence is fixed and there is NO replanning |
| Evidence acquisition | BUILT, all UNVERIFIED-LIVE: OpenAlex, EuropePMC, PubMed (E-utilities), arXiv, Crossref, NASA ADS, ClinicalTrials.gov, Semantic Scholar, CORE, DOAJ, GitHub (implementations only) |
| Claim extraction (claims, methods, results) | BUILT: rules + LLM with verbatim-quote grounding. Methods/results as separate typed objects: NOT BUILT |
| Citation extractor | PARTIAL: DOIs from reference list only |
| Table parser | BUILT (PyMuPDF find_tables + per-cell word reconstruction; feeds GRIM). OCR: NOT BUILT |
| Evidence verification: quality scorer | BUILT, but DEVIATES from PDFs: venue prestige and citation count are stored, not scored (they are not evidence of correctness) |
| Contradiction detector | BUILT (triple-level + belief-level) |
| Fact checker | PARTIAL: p-value recomputation, GRIM, equation checks. Cross-referencing "known databases" and physical-law checks: NOT BUILT |
| Human-in-the-loop | BUILT (`/beliefs/{id}/feedback`: dispute / invalidate / restore, audited) |
| Veracity Gate | BUILT (policy threshold, configurable) |
| Belief engine | BUILT (versioned, auditable, dependency-aware; uncalibrated) |
| Hypothesis generator: gaps, contradictions, TransE link-prediction rank | BUILT (TransE only trains when the graph has >=15 triples). Trends, abductive reasoning: NOT BUILT |
| Generate/critique/rank tournament loop (Co-Scientist style) | BUILT, LLM-only (critic drop/revise with variable-drift guard, pairwise tournament). Opinion-based and unvalidated; UNVERIFIED-LIVE |
| Hypothesis ranker | PARTIAL: novelty, evidence, testability (unweighted Borda). Feasibility and impact are not scored |
| Hypothesis verifier (literature, contradiction) | BUILT. Physical/biological plausibility check: NOT BUILT |
| Experiment planner | BUILT (design, variables, power-analysis sample size, success/failure criteria, ethics) |
| Report with coverage matrix + gap analysis | BUILT (query mode); 25-section report (document mode) |

## Engines
| Engine | Status |
|---|---|
| Statistical (p-values, GRIM, power, meta-analysis, Monte Carlo) | BUILT |
| Logical | BUILT (SAT + unsat core). Prolog / ontologies (SNOMED, UMLS): NOT BUILT |
| Temporal | BUILT (stance trend over publication year, Kendall tau; refuses < 4 dated points). Time-series models (ARIMA/LSTM): NOT BUILT |
| Knowledge validation | BUILT as deterministic belief checks (single lineage, unknown design, causal claim without interventional design, gate-passed-but-contested). Lean/Coq proof obligations: NOT BUILT |
| Causal | BUILT: backdoor criterion, causal-wording audit. DoWhy estimation / do-calculus: NOT BUILT |
| Mathematical | BUILT (sandboxed SymPy, equation equivalence, dimensional analysis). Optimization solvers: NOT BUILT |
| Graph | BUILT: gap/chain detection, contradiction clusters, TransE link prediction. GraphSAGE/GNN: NOT BUILT |
| Simulation | BUILT for explicit-equation ODEs and Newtonian two-body orbits (with conservation checks); refuses everything else. OpenFOAM/SPICE/molecular dynamics/climate: NOT BUILT |
| Validation/Critic engine | PARTIAL: hypothesis verification checks + LLM critic. Domain engines (chemistry): NOT BUILT |

## Infrastructure
| Item | Status |
|---|---|
| FastAPI backend, PostgreSQL/SQLite, S3/MinIO storage, Docker | BUILT |
| Frontend | BUILT as a dependency-free page (Ask, Upload, Claims, Beliefs, Hypotheses, Graph, Report, Corpus, System). React/Next.js, Cytoscape/D3: NOT BUILT |
| Neo4j graph DB | NOT BUILT (NetworkX in-process; Postgres is source of truth) |
| Retrieval | BUILT: TF-IDF + LSA hybrid in-process; optional dense embeddings via sentence-transformers (hook only, untested here). Milvus/Chroma/pgvector: NOT BUILT. Blend weights and LSA size are untuned |
| Job queue | BUILT: durable DB-backed queue + `noesis worker` (lease/re-claim after crashes, attempt cap, SKIP LOCKED on Postgres). Celery/Redis/Ray/Kafka, microservices, Kubernetes, Airflow: NOT BUILT (`noesis refresh` CLI is the scheduler hook) |
| Auth | BUILT: accounts (scrypt), signed expiring tokens, admin/researcher roles, per-user project isolation. OAuth/OIDC federation and password reset: NOT BUILT |
| Monitoring | PARTIAL: `/metrics` (Prometheus text). Grafana dashboards, tracing, MLflow: NOT BUILT |
| Remaining connectors: PatentsView, NIH RePORTER, WHO, Data.gov, PMC full text, web scrapers | NOT BUILT |
| Evaluation | BUILT as a harness (`noesis eval scifact|triples`, bootstrap CIs). NO RESULTS EXIST YET: it needs SciFact data and, for the LLM column, your key. Expert ratings and the vs-RAG baseline: NOT BUILT |
| Model fine-tuning / retraining from feedback | NOT BUILT |

## Added beyond the PDFs (engineering hardening, requested via the system-design / debug / mcp-builder skills)
| Item | Status |
|---|---|
| MCP server (24 tools, stdio + streamable HTTP, annotations, pagination, actionable errors, evaluation set) | BUILT and tested end to end against the real API; never connected to a real MCP host app |
| Rate limiting, upload caps, page cap, active-job guard, login hardening | BUILT (per-process limiter) |
| Savepoint-isolated tasks, atomic job claim, SQLite WAL/lock retry, resilient worker loop | BUILT, stress-tested |
| Index memory/latency fix with measured benchmark | BUILT (`scripts/bench_index.py`) |
| System design doc and debug report | `docs/SYSTEM_DESIGN.md`, `docs/DEBUG_REPORT.md` |

## Gap-fix pass (readiness audit, 133 tests)
| Item | Status |
|---|---|
| Query path calls the engines by question type; `not_applicable` instead of silence | BUILT, tested |
| Evidence lineage by shared authors (replaces first-author-surname proxy; conservative) | BUILT, tested end to end. Document mode still uses the old proxy |
| Directional seed hypotheses (increase and decrease both tested) when the question gives no direction | BUILT, tested |
| Append-only belief history; claims need text; evidence needs a source (DB triggers) | BUILT and tested on SQLite. PostgreSQL versions written, NEVER run against a real server |
| Job lease heartbeat | BUILT, tested |
| Still NOT done (needs real data, network or a model): measured quality, live connector runs, calibration, full-text chunking, cross-encoder reranker, dense-embedding tuning, replanning in query mode, Neo4j/vector DB, remaining connectors, Prolog/ontologies, DoWhy estimation, GNN, simulators beyond ODE/two-body |

## Build pass 2 (157 tests)
| Item | Status |
|---|---|
| Replanning in query mode (broader queries when evidence is below target; synonyms first, then each side of the claim, then concepts; bounded by `max_replans`; every round recorded in `result.plans`) | BUILT, tested. Lineage is recomputed across rounds |
| BM25 + reciprocal-rank-fusion reranker over first-stage candidates (BM25 weighted 2x) | BUILT, wired into corpus search (`NOESIS_RERANK`), tested. Lexical only: NOT a cross-encoder, not semantic |
| Section-aware sentence-aligned chunker (`corpus/chunk.py`) | BUILT, tested as a library. NOT yet wired into full-text retrieval: uploaded documents are still retrieved by claim/sentence |
| Connectors: NIH RePORTER, PatentsView (needs API key), Data.gov, Europe PMC open-access full text | BUILT against the public API shapes, tested with recorded-style mock responses. NEVER run against the live services. Grants, patents and datasets are stored as `non_evidence` and never counted as evidence |
| WHO GHO | NOT built: WHO announced a replacement for the OData API; build against the new one when it is documented |
| Ontology loader (OBO) + exact-match annotation; synonyms feed query broadening; `noesis ontology --file --name` | BUILT, tested. No ontology is bundled or seeded: you load a real file |
| Neo4j projection (idempotent MERGE only), `noesis project-graph --project N [--dry-run]` | BUILT, tested with a fake driver. NEVER run against a real Neo4j server |
| Causal effect estimation (linear OLS backdoor adjustment, bootstrap CI, naive vs adjusted, graph check) | BUILT, tested on synthetic data with a known true effect. Not DoWhy/EconML; no nonlinear or instrument-based estimators |
| Inline-tag stripping bug in connector abstracts ("data ." gap) | FIXED, affects every connector |
| CLI tests | ADDED (previously none) |

### Still NOT built (needs a model, a service, or real data)
Measured results of any kind; harvested corpus and gold labels; calibrated confidence; cross-encoder reranking and dense-embedding tuning; vector-database backend (Qdrant/pgvector); full-text retrieval over chunks; math/simulation routing in query mode; React frontend; Prolog/Lean reasoning; GNN link prediction; PostgreSQL guards verified on a real server.
