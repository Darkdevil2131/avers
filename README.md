# ARES / Noesis

A working evidence-first research workspace built from scratch. React and Three.js provide the browser interface; FastAPI and SQLite or PostgreSQL run the authenticated research workflow.

## Working features
- Named-user bearer authentication and project owner/editor/viewer access.
- Source snapshots, license metadata, SHA-256 provenance, exact passage offsets, and append-only source reviews.
- Bounded research runs with optional keyless Europe PMC collection, hybrid passage retrieval when models are prepared, live SSE events, persistent cited reports, cancellation, and crash recovery through the worker.
- Reviewer-entered claims with nine-field context fingerprints, exact evidence links, context mismatch handling, retraction awareness, and explicit uncalibrated assessment labels.
- Immutable hypothesis revisions with proposed mechanisms and falsification criteria.
- Audited descriptive statistics and dimension-checked unit conversion.
- A source graph, reduced-motion 2D view, source review interface, Markdown export, and backup integrity verification.
This release is a research workspace with policy-driven orchestration and optional local models. It does not yet implement the complete autonomous scientific intelligence design. Retrieval reports remain inconclusive; a matching passage is not proof. See [known limitations](docs/KNOWN_LIMITATIONS.md).
## Run in an existing hosted environment
Use Python 3.12+ and Node 22. Do not provision a paid host, enable billing, or start a trial. Development commands below run wherever the shell is hosted; running them on a laptop would use that laptop.
```bash
python -m venv .venv
.venv/bin/pip install -r requirements.lock
cd web
npm ci
npm test
npm run build
cd ..
.venv/bin/python -m pytest -q
```
Configure a unique random token of at least 32 characters for each user. Keep the environment variable secret and copy your token into the login form. Never commit it.
```bash
export ARES_CREDENTIALS="$(.venv/bin/python -c 'import json,secrets; print(json.dumps({"researcher": secrets.token_urlsafe(48)}))')"
export ARES_DATABASE=state/ares.db
.venv/bin/uvicorn ares.api:app_factory --factory --host 127.0.0.1 --port 8000
```
Open the hosted environment's authenticated port preview for port 8000. The generated frontend is served by FastAPI. `npm run build` is required before starting it. Built assets and dependency directories are reproducible outputs, excluded from source control.
For durable background processing, set `ARES_QUEUE_MODE=db` before starting the API and run `.venv/bin/python -m ares.cli worker` in a second process sharing `ARES_DATABASE`. One worker is recommended. Inline mode is convenient for development; interrupted inline jobs require the worker to recover them.
Use `/docs` or `/openapi.json` for the API schema. These expose endpoint definitions, not credentials or research content.
## Verification
```bash
.venv/bin/python -m pytest -q
cd web && npm test && npm run build
```
[Deployment](docs/DEPLOYMENT.md) · [Security](docs/SECURITY.md) · [Scientific validation](docs/SCIENTIFIC_VALIDATION.md) · [Costs](docs/COST_AND_INFRASTRUCTURE.md)
## Local model preparation (release 0.3)
The newer retrieval path includes real dense embeddings, reciprocal-rank fusion, and a cross-encoder reranker. Download model files explicitly on an existing hosted machine; runtime requests do not download them. Dependency telemetry is disabled before initialization.
```bash
.venv/bin/python scripts/prepare_models.py
# Optional local reasoning; no inference API subscription:
.venv/bin/pip install -r requirements-reasoner.txt
.venv/bin/python scripts/prepare_reasoner.py
export ARES_REASONER_MODEL="$PWD/state/reasoner/qwen2.5-1.5b-instruct-q4_k_m.gguf"
```
These commands use CPU, RAM and disk on the host where they run. Keep weights under state/ and never commit them. Missing models result in explicitly reported fallback modes. The small local model is fallible: generated answers must be exact extracts to appear as report text, while hypotheses are clearly unvalidated proposals.

The collector can follow permitted article references up to depth one/four full-text documents. Only explicitly recognized reuse licenses are ingested. Live retrieval of two licensed articles, original-content hashes, and passage locations passed on GitHub Actions. Europe PMC JATS has an approved NCBI BioC fallback. See docs/live-fulltext-verification.json.

The coordinator chooses a primary search when project evidence is absent, counterevidence search when matching passages exist, and a broader search when fewer than two records return. This is an explicit bounded policy. It does not establish that agents understand science.
Every report creates pending memory. Owners can approve/reject records and mark cited sources relevant/not relevant. Similar future queries can use that relevance feedback; the system does not train on its own responses as ground truth.
Reproducible model smoke checks after preparation:
```bash
PYTHONPATH=. .venv/bin/python scripts/evaluate_retrieval.py
PYTHONPATH=. .venv/bin/python scripts/smoke_local.py
```
See docs/ENGINEERING_PROGRESS.md for measured results, observed model failure, and outstanding work. The full master design and public production deployment remain incomplete.

## Verified infrastructure update

PostgreSQL now enforces project isolation using row-level security and separate application, worker, and migration roles. CI verifies unauthorized reads/writes, concurrent tenant reads, and API report creation against PostgreSQL 16. Container build/start and live full-text checks pass. See [deployment instructions](docs/DEPLOYMENT.md).

SciFact development evaluation covers 27 claims over 1,000 documents: retrieval recall@8 was 100%, first-candidate rationale agreement 66.7%, and candidate rationale precision 33.3%. This restricted development result is not proof of scientific reliability. A rerun on 30 distinct development claims achieved hybrid recall@8 of 96.7% and first-candidate rationale agreement of 63.3%; its results are now saved. Public deployment and expert scientific validation remain incomplete.

A real 30-user HTTP workload passes against SQLite and PostgreSQL. See [measured load results and limits](docs/LOAD_VALIDATION.md). These checks cover private reads and idempotent queue submissions, not sustained model inference or a deployed service.
