# Architecture

The same-origin React client keeps the access token in memory and sends authenticated fetch requests. FastAPI checks project membership for every data operation. SQLite stores sources, passages/FTS5, runs, leases, events, immutable reports, claims, evidence links, hypothesis revisions, and append-only audit records. Numbered idempotent SQL scripts initialize schemas. This is application-enforced isolation, not PostgreSQL RLS.

A run executes plan → optional Europe PMC metadata import → project passage retrieval → exact-span audit → report. Search is lexical and bounded to eight cited passages. No embedding model or language model runs. Background execution uses either FastAPI background tasks or a separate database-backed worker. Claiming a queued run uses an immediate transaction, with a 90-second lease and three-attempt ceiling. Reports and completion events commit together. Idempotency keys prevent duplicate submissions with the same payload.

Science review is a separate human-entered workflow. Claim/evidence context compares nine explicit fields. Missing fields remain unverified; differing fields are context-mismatched. Report retrieval detects later source review changes. Hypothesis revisions reference predecessors without rewriting history.

External traffic is limited to a fixed HTTPS Europe PMC metadata endpoint. User-provided source URLs are stored as provenance and never fetched. Arbitrary uploaded executables, PDFs, and URLs are not accepted for processing. Calculation tools have fixed typed behavior with no eval, shell, or generated-code execution.
