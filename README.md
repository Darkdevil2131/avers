# ARES / Noesis

A working evidence-first research workspace built from scratch. React and Three.js provide the browser interface; FastAPI and SQLite run the authenticated research workflow.

## Working features

- Named-user bearer authentication and project owner/editor/viewer access.
- Source snapshots, license metadata, SHA-256 provenance, exact passage offsets, and append-only source reviews.
- Bounded research runs with optional keyless Europe PMC bibliographic search, lexical passage retrieval, live SSE events, persistent cited reports, cancellation, and crash recovery through the worker.
- Reviewer-entered claims with nine-field context fingerprints, exact evidence links, context mismatch handling, retraction awareness, and explicit uncalibrated assessment labels.
- Immutable hypothesis revisions with proposed mechanisms and falsification criteria.
- Audited descriptive statistics and dimension-checked unit conversion.
- A source graph, reduced-motion 2D view, source review interface, Markdown export, and backup integrity verification.

This release is a functioning deterministic research workspace. It does not yet implement the complete autonomous scientific intelligence design. Retrieval reports remain inconclusive; a matching passage is not proof. See [known limitations](docs/KNOWN_LIMITATIONS.md).

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
