# Security boundary

Credentials are distinct, named, at least 32 characters, supplied through environment configuration, hashed for constant-time comparison, and absent from repository files. The frontend retains tokens only in memory. All project resources authorize membership; owners manage membership and read audit logs, editors write, viewers read. The 512 KiB body limit and 60 writes/searches per minute per authenticated user bound ordinary requests. Source text is untrusted data and rendered as escaped React text. CSP restricts script and connection origins. Source provenance links allow only HTTP(S).

No arbitrary network fetch, shell execution, PDF parser, pickle loader, model tool calling, or cross-project retrieval exists. SQL uses bound parameters, and FTS terms are sanitized. Snapshots and audit records have SQLite triggers preventing ordinary UPDATE/DELETE operations. Database administrators can alter the database; these controls are not cryptographic tamper proofing.

Current deployment scope is a private hosted workspace. Before public production: add TLS termination, secret rotation/session lifecycle, ingress rate limits for invalid authentication, storage quotas, persistent encrypted volumes, operational monitoring, abuse testing, and stronger concurrent/multi-instance isolation. The current app is not approved for sensitive medical or regulated data.
