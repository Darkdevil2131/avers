# Known limitations

The product is not complete or ready to claim scientific reliability.

- The coordinator makes bounded policy decisions from existing passages and search-result counts. It is not a generally intelligent autonomous research team.
- Hybrid retrieval and reranking use real pretrained models, but scientific retrieval recall has not been independently evaluated. Dense retrieval currently scans at most 2000 active project passages; beyond that it visibly uses lexical retrieval. This is a bounded single-host implementation.
- Full-text ingestion supports explicitly recognized CC BY/CC BY-SA/CC0 JATS documents through the fixed Europe PMC API. Live validation is blocked in this environment. No general unrestricted crawler, PDF/OCR ingestion, automatic retraction registry, or multi-provider source coverage exists.
- Claim candidates are extracted with sentence patterns. No expert-labeled precision/recall or automatic causal/context verification exists. Normalized manual context comparisons do not understand synonyms or unit equivalence.
- Local Qwen inference is real but small and fallible. A test produced an unsupported mechanism; the narrative was rejected by the revised report policy. Exact quotes establish provenance only. Generated mechanisms and falsification proposals remain unvalidated and may be wrong.
- Scientific report assessments still abstain. The system does not establish fraud, fabrication, novelty, scientific proof, or safety of an experiment.
- Each response creates pending memory. Approved memory is available for review; owner relevance feedback can adjust dense retrieval for similar questions. No automatic training on self-generated text or model-weight learning occurs.
- SQLite authorization is application-enforced, not PostgreSQL RLS. Source budgets are 1000 snapshots/20 million characters per project; ingress abuse prevention and production multi-instance isolation remain incomplete.
- Optional model files require preparation on the host. No automatic model download happens during requests; missing models are disclosed. The host must have sufficient CPU/RAM/storage. These resources are not guaranteed to be available indefinitely free.
- No public production deployment, Docker build validation, visual browser/WebGL acceptance, or scientific expert validation has been completed.
