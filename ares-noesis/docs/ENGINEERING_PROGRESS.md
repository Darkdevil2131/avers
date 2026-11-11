# Engineering progress

## Stage 0 — Discovery

Reviewed the attached 31-page master design and the supplied noesis_9 archive against the empty GitHub repository. The archive already includes document and question workflows, a corpus, evidence and belief tracking, a leased worker, user accounts and MCP. Identified fail-open API defaults, unprotected first administrator registration, project-wide hypothesis deletion and retraction cache collisions.

## Stage 1 — Secure foundation in progress

API startup requires credentials. Initial administrator registration requires the bootstrap key. The default runtime is offline, direct reasoning endpoints require operator privileges and the app avoids automatic paid model, object storage and graph services. New hypothesis and report records carry job identifiers, and retraction-set changes invalidate the corpus index.

## Dependency-ordered backlog

1. Add an isolated parser and versioned PostgreSQL migration, authorization and restore tests.
2. Verify provider terms and live metadata access, then ingest immutable source versions and spans.
3. Benchmark retrieval and scientific context matching on materials degradation literature.
4. Gate report conclusions on exact citations and independent study evidence.
5. Add budgeted orchestration, expert review, research memory controls and event-driven UI.
6. Run benchmarks, failure injection and security acceptance tests before considering a public zero-billing deployment.

## Verification

- Archive baseline in the isolated hosted Python 3.12 environment: 155 passed and 2 failed because the MCP client implicitly used the host's SOCKS proxy. The bundled client now connects directly to its configured API.
- Updated suite: 163 passed, including bootstrap authorization, tenant access checks, database queue recovery, retraction invalidation and hypothesis history retention. One dependency deprecation warning remains.
- Dependency consistency: pip check passed.
- Hosted HTTP smoke passed for health, anonymous 401, authenticated project creation, offline question processing and persisted report retrieval.
