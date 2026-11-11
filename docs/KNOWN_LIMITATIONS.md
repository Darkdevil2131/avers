# Known limitations

- This is a working deterministic release, not the whole autonomous ARES research blueprint.
- No semantic embeddings, vector retrieval, reranking, LLM planning, automated scientific stance inference, self-training, causal engine, simulation framework, or independent agent collaboration is implemented.
- Europe PMC search imports bibliographic metadata only. No arbitrary crawler, licensed full-text ingestion, PDF OCR, tables/figures parser, or automatic retraction registry synchronization exists.
- Claim context and evidence stance are reviewer-entered. Exact normalized context matching cannot understand synonyms or unit equivalence. Study IDs do not prove independent evidence.
- SQLite application authorization is not PostgreSQL row-level security. Per-process rate limits, SQLite concurrency, and no hard storage quota limit public deployment readiness.
- Credentials require operator provisioning and rotation. Membership management is API-only. Unit conversion is API-only; the UI exposes sample statistics.
- No always-on free hosting, cloud storage backup, Docker image build verification, or production load test has been completed.
- Component interaction tests and production compilation pass. Full browser visual/mobile/WebGL testing was blocked by sandbox browser launch and cloud-to-local connectivity restrictions. The Three.js lazy-loaded bundle exceeds Vite's 500 kB warning threshold.
