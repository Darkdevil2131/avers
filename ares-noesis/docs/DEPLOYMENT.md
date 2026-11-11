# Hosted development

Use a remote Linux x86_64 workspace with Python 3.12. Install from `requirements.lock` and set a random key in the remote environment. The included container definition uses a non-root user, a SQLite volume and a loopback-only host port. The development deployment has no public endpoint.

```bash
cd ares-noesis
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pytest -q
export NOESIS_API_KEY="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
.venv/bin/python -m noesis.cli serve
```

`GET /health` verifies API liveness. Send `X-API-Key` for protected routes in single-operator mode. For account mode, set `NOESIS_AUTH_MODE=users`, generate a separate random `NOESIS_SECRET_KEY`, and send the bootstrap API key to `POST /api/v1/auth/register` for the initial administrator. Keep registration closed except during intentional onboarding.

To exercise the durable queue, set `NOESIS_QUEUE_MODE=db` for the API and run `python -m noesis.cli worker` in a second process sharing the hosted database and blob directory. Before upgrading an archive database, stop writers and preserve the SQLite database and blob directory. Legacy rows remain accessible to the operator or administrator. Additive migration creates the new schema fields on startup.
