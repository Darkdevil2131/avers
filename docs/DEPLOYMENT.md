# Deployment and operations

See README for a hosted-shell run. Only use an existing authorized environment with no additional charge. Browser preview remains private. No public production site has been deployed.

Docker packaging uses Node 22 to compile the client and a Python 3.12 runtime under UID 10001. Pass ARES_CREDENTIALS through the host's secret environment and mount a writable persistent directory at /app/state. Expose through an authenticated HTTPS proxy; do not publicly expose port 8000 unprotected. Container construction requires dependency network access. Docker build and application health startup passed GitHub Actions run 43002167894. This does not verify a public deployment.

For the durable queue use ARES_QUEUE_MODE=db in the API and run python -m ares.cli worker sharing the database. Keep one worker initially. Do not deploy this SQLite file on ephemeral serverless storage or a shared network filesystem. Inline mode does not automatically restart interrupted jobs; start the worker to recover them.

Backup commands:

```bash
python -m ares.cli backup --file backups/ares-new.db
python -m ares.cli verify-backup --file backups/ares-new.db
```

Backups use SQLite's online backup API and verify integrity and foreign keys. For restore, stop API/worker, preserve the existing database and its WAL/SHM files separately, then copy a verified backup to ARES_DATABASE and restart. Tests restore into a separate database and read retained report data. Retain access secrets separately; they are not in the backup.

Schema scripts are additive and idempotent. Roll back code only after checking schema compatibility, or restore a pre-upgrade backup. Migration downgrade tooling and production recovery objectives remain unimplemented.

Optional dense and generative models require explicit preparation described in README, a persistent state/models and state/reasoner volume, and sufficient host resources. The base Docker recipe includes dense dependencies but not optional llama.cpp bindings; install requirements-reasoner.txt in an explicitly selected image variant before enabling ARES_REASONER_MODEL. No model or hosting cost is hidden behind startup. This configuration is not yet a tested production deployment.

## PostgreSQL deployment on an existing authorized host

The supplied compose.yaml separates database, administrator migration, API, and worker services. The database has no published port; the API binds localhost only. Put an authenticated HTTPS proxy in front of it before any public access. The API and worker run without added capabilities on read-only root filesystems, with writable state volumes and temporary directories. The compose-workflow CI job now exercises the full API/database/worker topology and persistence after restart; check the latest run before deploying. It excludes optional generative models.

Use a dedicated PostgreSQL database. Supply these through the host's secret environment, never committed files:

- ARES_DB_ADMIN_PASSWORD and ARES_ADMIN_DATABASE: database initialization and migration only.
- ARES_DB_APP_PASSWORD and ARES_APP_DATABASE: distinct ares_app password and DSN.
- ARES_DB_WORKER_PASSWORD and ARES_WORKER_DATABASE: distinct ares_worker password and DSN.
- ARES_CREDENTIALS: JSON mapping of user names to independent random bearer tokens.

Passwords must have at least 32 characters. Encode passwords correctly in connection URLs. The Compose database hostname is database, port 5432, database ares. Do not use the administrator DSN for application requests. Start with docker compose up --build -d only on an already authorized no-charge host. This command does not provision a cloud account, but its host still needs capacity and durable storage.

Prepare models explicitly in the shared state volume via the worker service (which has outbound access). For optional local reasoning, build the image with WITH_REASONER=1 and set ARES_REASONER_MODEL to the prepared GGUF file. Missing weights are disclosed; no paid inference fallback exists.

For PostgreSQL, use pg_dump and restore into a separate database with psql -v ON_ERROR_STOP=1. The SQLite CLI backup commands deliberately refuse PostgreSQL DSNs. CI restores a disposable database and checks retained reports plus RLS isolation as the restricted application role. Database dumps do not back up cluster-wide role passwords or external model volumes: retain role provisioning, secrets, and model manifests separately. Measure recovery time and backup retention on the actual deployment before claiming production recovery objectives.

No permanent no-charge host is connected. No trial, billing change, or paid deployment has been authorized or executed.

The API uses an ingress network in addition to the private database network so the localhost-only published port is reachable. This permits API egress; it is not an egress firewall. PostgreSQL remains unpublished on the internal network. A public host still needs an HTTPS proxy and operational controls.

## Queue admission and worker failure isolation

A project can have at most 20 uncancelled queued/running jobs. New submissions above that limit return HTTP 429 with Retry-After: 10. Existing matching idempotency keys still return the existing run at capacity; cancellation or completion releases a slot. Admission is serialized per project using a PostgreSQL transaction advisory lock, or SQLite's write transaction, so simultaneous requests cannot overfill the limit. This is a per-project bound, not a global resource quota or an inference-capacity guarantee.

A job failure remains visible as failed, but the worker loop continues to other jobs. Repeated iteration errors use exponential backoff from one to 30 seconds; logs record exception types without source text or connection URLs. SIGTERM/SIGINT request shutdown between jobs and interrupt idle/backoff waits. An in-flight operation may still need its existing deadline or lease recovery after a forced stop. API and worker containers have a bounded on-failure restart policy (five attempts). There is no paid service or additional provisioning involved.

Report publication is fenced by the current attempt number and unexpired lease. The final transaction locks the run row and rechecks ownership before writing a report, completed status, audit event or pending memory. An expired/replaced worker cannot publish or change a completed replacement to failed; an exception after cancellation cannot change cancelled to failed. Expired work can be reclaimed under the existing three-attempt budget. This does not terminate an already running model call or undo source collection performed before lease loss.

## Request admission and event streaming

Each API process admits at most 64 simultaneous HTTP requests, including uploads and SSE streams. Excess concurrency returns 503 with Retry-After: 1. Before reading a body or checking credentials, a peer has a sliding budget of 6,000 requests per minute. The peer table holds at most 128 live identities; further identities are rejected until expired entries are cleaned up. Exceeded admission budgets return 429. The existing authenticated write/search budget remains 60 per minute per user. These are conservative per-process bounds, not a distributed DDoS defense or a production capacity claim.

Bodies remain limited to 512,000 bytes and must arrive within a total 15-second deadline, including chunked bodies; progress does not reset the timer. Timeout returns 408. Admission capacity is released on cancellation and failures. Public ingress still needs connection/header timeouts, TLS and shared limits across replicas. Requests through the same proxy may share a peer budget. The application does not parse X-Forwarded-For; configure ASGI forwarded-header trust only for known proxy addresses, never all Internet clients. Health checks use the same admission bounds.

SSE database polling runs in the thread pool with the authenticated request context preserved, rather than blocking the event loop. Polls continue to authorize project membership. The public /health endpoint returns a sanitized 503 on a database failure; it does not attest to worker or model readiness.

## Release boundary

Keep the hard no-charge/no-trial requirement. Do not attach a new paid service, enable paid inference or provision hosting to satisfy a failing check. Before deploying this branch, inspect the existing Railway plan and usage and verify whether GitHub branch/PR changes trigger billable deployments. Publishing a branch is not a verified Railway rollout. The live host, model resources, durable volumes, backup recovery, HTTPS and sustained inference workload still require verification. Scientific selection results in SCIENTIFIC_VALIDATION.md and IMPROVEMENTS_2026_11_12.md remain unchanged by operational hardening.
