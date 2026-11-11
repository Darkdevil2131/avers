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

The supplied compose.yaml separates database, administrator migration, API, and worker services. The database has no published port; the API binds localhost only. Put an authenticated HTTPS proxy in front of it before any public access. The API and worker run without added capabilities on read-only root filesystems, with writable state volumes and temporary directories. The full Compose topology has not yet been acceptance-tested.

Use a dedicated PostgreSQL database. Supply these through the host's secret environment, never committed files:

- ARES_DB_ADMIN_PASSWORD and ARES_ADMIN_DATABASE: database initialization and migration only.
- ARES_DB_APP_PASSWORD and ARES_APP_DATABASE: distinct ares_app password and DSN.
- ARES_DB_WORKER_PASSWORD and ARES_WORKER_DATABASE: distinct ares_worker password and DSN.
- ARES_CREDENTIALS: JSON mapping of user names to independent random bearer tokens.

Passwords must have at least 32 characters. Encode passwords correctly in connection URLs. The Compose database hostname is database, port 5432, database ares. Do not use the administrator DSN for application requests. Start with docker compose up --build -d only on an already authorized no-charge host. This command does not provision a cloud account, but its host still needs capacity and durable storage.

Prepare models explicitly in the shared state volume via the worker service (which has outbound access). For optional local reasoning, build the image with WITH_REASONER=1 and set ARES_REASONER_MODEL to the prepared GGUF file. Missing weights are disclosed; no paid inference fallback exists.

For PostgreSQL, use pg_dump and restore into a separate database with psql -v ON_ERROR_STOP=1. The SQLite CLI backup commands deliberately refuse PostgreSQL DSNs. CI restores a disposable database and checks retained reports plus RLS isolation as the restricted application role. Database dumps do not back up cluster-wide role passwords or external model volumes: retain role provisioning, secrets, and model manifests separately. Measure recovery time and backup retention on the actual deployment before claiming production recovery objectives.

No permanent no-charge host is connected. No trial, billing change, or paid deployment has been authorized or executed.
