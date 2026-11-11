# Engineering status — 2026-11-11

Built from scratch: authenticated API, scoped project/source storage, FTS retrieval, Europe PMC metadata adapter, bounded persistent research workflow, SSE, exact cited reports, retractions, context-aware reviewer evidence, hypothesis revisions, deterministic tools, backup verification, and React/Three.js workspace.

Validation: 22 backend tests and 3 frontend interaction tests passed; Vite production build passed. A warning remains for the large lazy-loaded Three.js chunk. Full browser screenshot/WebGL/mobile verification is blocked by this environment and remains uncompleted. Docker recipe and public production hosting are not validated. CI configuration repeats backend, frontend, and build checks on standard public-repository runners.

See REQUIREMENTS.md and KNOWN_LIMITATIONS.md for incomplete master-design capabilities. No paid infrastructure or inference has been enabled.
