# Deployment and operations

See README for a hosted-shell run. Only use an existing authorized environment with no additional charge. Browser preview remains private. No public production site has been deployed.

Docker packaging uses Node 22 to compile the client and a Python 3.12 runtime under UID 10001. Pass ARES_CREDENTIALS through the host's secret environment and mount a writable persistent directory at /app/state. Expose through an authenticated HTTPS proxy; do not publicly expose port 8000 unprotected. Container construction requires dependency network access. The Docker recipe is supplied but has not been built in this restricted environment.

For the durable queue use ARES_QUEUE_MODE=db in the API and run python -m ares.cli worker sharing the database. Keep one worker initially. Do not deploy this SQLite file on ephemeral serverless storage or a shared network filesystem. Inline mode does not automatically restart interrupted jobs; start the worker to recover them.

Backup commands:

```bash
python -m ares.cli backup --file backups/ares-new.db
python -m ares.cli verify-backup --file backups/ares-new.db
```

Backups use SQLite's online backup API and verify integrity and foreign keys. For restore, stop API/worker, preserve the existing database and its WAL/SHM files separately, then copy a verified backup to ARES_DATABASE and restart. Tests restore into a separate database and read retained report data. Retain access secrets separately; they are not in the backup.

Schema scripts are additive and idempotent. Roll back code only after checking schema compatibility, or restore a pre-upgrade backup. Migration downgrade tooling and production recovery objectives remain unimplemented.
