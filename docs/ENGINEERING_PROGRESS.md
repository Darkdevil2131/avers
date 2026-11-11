# Engineering status — 2026-11-11

This repository is an incomplete research product under development. It must not be described as the complete ARES design or scientifically validated.

## Verified in the hosted workspace

- 31 backend behavior tests and 3 frontend interaction tests pass; frontend production compilation passes.
- MiniLM produces actual 384-dimensional embeddings. Retrieval combines FTS5, dense cosine candidates, reciprocal-rank fusion, and a local cross-encoder reranker.
- On ten synthetic paraphrase examples authored during implementation, lexical top-1 accuracy was 2/10, hybrid without reranking 5/10, and hybrid with reranking 10/10. These examples are not a held-out scientific benchmark. See retrieval-before-reranking.json and retrieval-smoke.json.
- Qwen2.5-1.5B-Instruct GGUF runs on the hosted CPU through llama.cpp with no paid inference service. A synthetic end-to-end example exercises retrieval, exact extraction, local generation, and report persistence.
- An earlier model test invented a direction of water-uptake change. The observed failure is retained in local-model-failure-observed.json. Generated answer narratives are now rejected unless they are exact source extracts. Hypotheses remain speculative, unvalidated proposals requiring expert review. Quote integrity does not establish semantic correctness.
- XML license checks, entity rejection, exact normalized-text locations, bounded citation traversal, cancellation, evidence review, memory review, and feedback scoping are covered by fixtures.

## Unverified or incomplete

- Live Europe PMC full-text requests were blocked by a network proxy 403. The full-text path is fixture-tested, not successfully live-validated here. Earlier live metadata search succeeded.
- No independent scientific benchmark, expert hypothesis assessment, causal verification, study-independence validation, model fine-tuning, PostgreSQL/RLS deployment, production scaling/load testing, or public hosting is completed.
- Full browser visual/mobile/WebGL testing and Docker construction remain unverified.

## Cost and privacy

No paid endpoint, trial, billing account, or cloud resource was enabled. Models were downloaded from public model repositories and executed in the existing hosted environment. ONNX telemetry was initially blocked by automatic approval review; the safer setup sets ORT_DISABLE_TELEMETRY=1 before runtime initialization, plus Hugging Face telemetry opt-out. No retry of the unchanged telemetry-enabled setup was used.

The final synthetic model run produced a candidate opposing its own cited observation. The consistency critic rejected that candidate and recorded the reason; the final report retained an extractive answer and a clearly labeled replication proposal. These deterministic rejection checks are narrow and do not certify other generated mechanisms.
