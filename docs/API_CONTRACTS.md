# API contracts

The generated /openapi.json is authoritative for fields and response codes. All data endpoints require Authorization: Bearer <token>. GET /health is a minimal public health response. POST requests use JSON.

| Resource under /projects/{project_id} | Operations |
| --- | --- |
| /sources | GET list, POST immutable source |
| /sources/{id}/review | POST active/retracted/excluded review |
| /search?q=... | GET scoped passages |
| /runs | GET history, POST question/external with optional Idempotency-Key |
| /runs/{id} | GET durable status |
| /runs/{id}/stream | GET authenticated SSE |
| /runs/{id}/report | GET saved report and current staleness |
| /runs/{id}/cancel | POST cancel |
| /claims | GET assessed claims, POST statement/fingerprint |
| /claims/{id}/evidence | POST exact offsets, stance, fingerprint, rationale |
| /hypotheses | GET history, POST versioned proposal |
| /tools/{name} | POST parameters |
| /audit | GET owner-only audit history |

GET/POST /projects lists/creates projects; GET /session identifies the caller; GET /capabilities describes calculations. Unauthorized project actions return 404 to avoid disclosing membership. Invalid authentication returns 401, conflicting idempotency 409, excessive bodies 413, invalid data 422, and request budgets 429.
