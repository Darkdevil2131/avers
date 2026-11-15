# Local inference workload, 2026-11-15

This is a reproducible engineering check, not scientific validation or a release certification. It exercised a localhost HTTP API, one database-queue worker, a disposable SQLite database, hybrid retrieval, and the pinned Qwen2.5-1.5B-Instruct Q4 model. Three users each submitted three jobs in three batches; the sources were synthetic variations of one coating-adhesion scenario. The model ran in a cloud workspace, not on the user's computer. It was downloaded with TLS verification and checked against the project's pinned SHA-256.

With the existing prompt, nine of nine jobs completed, returned the exact synthetic source quote, and recorded a completed reasoner call. The existing critic rejected all nine generated candidate hypotheses because they reversed the observed direction; some also disclaimed their own evidential support. Queue-to-report time was 11.24–32.62 seconds; the total run was 93.06 seconds. Health requests were observed during the run. These numbers describe this particular test environment and workload only. The result is recorded in [inference-soak-2026-11-15.json](inference-soak-2026-11-15.json).

An experimental instruction to preserve the observed direction was then tested against the same fixture. Six of nine candidates were still rejected for opposing their cited observation; three were not flagged by this limited critic. That does not establish that those three were correct, or that the instruction generalizes. The experimental prompt was **not shipped**. Its result is preserved in [inference-soak-prompt-experiment-2026-11-15.json](inference-soak-prompt-experiment-2026-11-15.json).

The model can complete a call while its candidate is rejected. `all_inferences_completed` only reports completion of the reasoner calls, not scientific correctness or acceptance. The critic is a limited rule-based safeguard, not a substitute for expert review.

To repeat, install the project's local reasoner and retrieval dependencies, prepare the pinned model with `scripts/prepare_reasoner.py`, and run with the model and cache paths set for your environment:

```sh
ARES_REASONER_MODEL=/path/to/model.gguf ARES_MODEL_CACHE=/path/to/model-cache \
  HF_HUB_OFFLINE=1 PYTHONPATH=. python scripts/inference_soak_check.py \
  --users 3 --rounds 3 --output /path/to/new-result.json
```

The output path must not already exist. This test does not measure memory, validate PostgreSQL isolation or backups, test a deployed site, establish capacity for 30 users, assess scientific quality on independent expert-labeled evidence, or prove free permanent hosting. Those remain open release requirements. No paid service or trial was used in these runs.
