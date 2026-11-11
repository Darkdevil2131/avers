# Engineering decisions

SQLite and standard-library retrieval keep this release runnable without hosted database or inference subscriptions. Bearer credentials and a same-origin frontend keep the private-workspace deployment small. No automatic cloud provisioning or spending fallback exists. Optional models run locally on the existing host without inference API calls.

Reports stay inconclusive because lexical retrieval cannot establish scientific validity. Human evidence review is explicit and separate. Hypothesis proposals retain revision history and never claim an experiment ran. Exact source offsets and immutable snapshots support reproducibility.

Generated frontend bundles are rebuilt from npm's lockfile. The optional Three.js module loads only for the visual graph; a reduced-motion 2D mode remains available. Source code, tests, schema scripts, and documentation are versioned; credentials, runtime data, dependencies, and generated bundles are excluded.
