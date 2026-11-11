# Architecture

The target is an evidence-first research system with lawful retrieval, immutable provenance, contextual evidence appraisal, validated reasoning tools, bounded agents and reviewed scientific memory.

The first increment uses FastAPI and SQLite in the hosted workspace. Authentication is checked before each scoped operation. SQLite guards preserve source and run records. Named API credentials are supplied through the environment. SQLite is a development choice pending PostgreSQL access controls and migration tests.

Start in a remote Python 3.12 environment with dependencies from requirements.lock, configure ARES_CREDENTIALS as a JSON mapping of user names to distinct random tokens of at least 32 characters, then run uvicorn ares.api:app_factory --factory --host 127.0.0.1. Send Authorization: Bearer TOKEN. Generated OpenAPI documentation describes the routes.

Public exposure is pending rate limits, request size limits, session management and deployment verification.
