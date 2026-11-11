# Known limitations

The product is not complete or ready to claim scientific reliability.

- The coordinator makes bounded policy decisions from existing passages and search-result counts. It is not a generally intelligent autonomous research team.
- Hybrid retrieval and reranking use real pretrained models, but evaluation is limited to a restricted SciFact development subset, with no independent final acceptance. Dense retrieval currently scans at most 10000 active project passages; beyond that it visibly uses lexical retrieval. This is a bounded single-host implementation.
- Full-text ingestion supports explicitly recognized CC BY/CC BY-SA/CC0 JATS documents through fixed Europe PMC JATS and NCBI BioC APIs. Two real full-text articles passed provenance checks. No general unrestricted crawler, PDF/OCR ingestion, automatic retraction registry, or broad cross-disciplinary source coverage exists.
- Claim candidates use sentence reranking when models are available, with a pattern fallback. Restricted SciFact rationale precision is only 33.3%; no automatic causal/context verification exists. Normalized manual context comparisons do not understand synonyms or unit equivalence.
- Local Qwen inference is real but small and fallible. A test produced an unsupported mechanism; the narrative was rejected by the revised report policy. Exact quotes establish provenance only. Generated mechanisms and falsification proposals remain unvalidated and may be wrong.
- Scientific report assessments still abstain. The system does not establish fraud, fabrication, novelty, scientific proof, or safety of an experiment.
- Each response creates pending memory. Approved memory is available for review; owner relevance feedback can adjust dense retrieval for similar questions. No automatic training on self-generated text or model-weight learning occurs.
- SQLite authorization is application-enforced. The PostgreSQL backend adds database RLS and separate runtime roles, tested with concurrent tenant reads. Source budgets are 1000 snapshots/20 million characters per project; ingress abuse prevention and production multi-instance isolation remain incomplete.
- Optional model files require preparation on the host. No automatic model download happens during requests; missing models are disclosed. The host must have sufficient CPU/RAM/storage. These resources are not guaranteed to be available indefinitely free.
- Container build and startup pass CI. No public production deployment, visual browser/WebGL acceptance, production load certification, or scientific expert validation has been completed.
