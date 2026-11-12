# Evidence selection and deployment workflow improvements

## Concrete changes

Fixed-size passage retrieval could return a sentence fragment. Retrieval now expands the passage edges to sentence boundaries within a bounded 1,200-character allowance per edge, retaining both original retrieval offsets and exact expanded source offsets. Long sentences outside that allowance can still be clipped. Sentence splitting preserves decimal numbers and common abbreviations and recognizes lowercase sentence starts. Duplicate expanded spans are removed. The extraction candidate budget is now global across citations rather than restarting at each citation.

When a cross-encoder passage score exists, candidate selection uses 75% sentence relevance and 25% passage relevance. Without passage scores it uses sentence relevance alone; without prepared models the existing visible pattern fallback remains. These scores are ranking heuristics, not probabilities of truth, entailment or scientific support. Statements remain exact extracts and reports still abstain from scientific verdicts.

## Measured outcomes, including regressions

| Comparison | First candidate matches | Precision across returned candidates |
| --- | --- | --- |
| Existing 30 claims, old pipeline | 19/30 | 36.7% |
| Existing 30 claims, boundary-only change | 19/30 | 35.6% |
| Existing 30 claims, final change | 20/30 | 37.8% |
| Different 24 claims, old pipeline | 8/24 | 30.6% |
| Same different 24 claims, final change | 10/24 | 27.8% |

The boundary-only change did not improve first-choice accuracy. The final change improves first-choice matches in both paired samples, but reduces overall candidate precision in the new sample. This is a tradeoff, not a general accuracy win. These small samples do not establish a statistically reliable improvement or scientific production readiness.

The new 24 claims exclude all 57 earlier claim IDs. The final pipeline was frozen before the new sample ran; no parameter sweep was performed on it. Both samples still come from the public SciFact development split, use restricted 1,000-document corpora, and may share corpus documents. The updated pipeline retrieved a gold document within eight passages for all 24 new claims. Neither retrieval nor exact quotation verifies a hypothesis. Measurements use the existing sentence-containment rationale metric, not expert semantic judgment.

Full results: sentence-boundary-only-evaluation.json, sentence-boundary-evaluation.json, scifact-followup-v2.json and scifact-paired-followup-v2.json. The paired script loads the old extractor from pinned repository commit 29b2b88fd8b290bd0a09037b993ef5eba3c9ef90. Fetch that history before reproducing the comparison. A populated evaluation database/archive and prepared local model cache are required; there is no inference API.

## Actual workflow verification

live-workflow-verification.json records a real NCBI BioC article (PMC4383902), its license and original-content hash. The source is imported through the HTTP API into a temporary SQLite database. A separate worker uses the prepared local embedding and cross-encoder models and persists a report. All eight citation spans and all three finding spans match the source. The run took approximately 4.14 seconds after collection. The test query uses the article title and does not measure answer correctness. Optional generative reasoning was explicitly disabled and reported unavailable.

A separate GitHub Compose test starts PostgreSQL, migration, API and worker containers. It checks queued report completion, citation hashes/offsets, pending memory, denied cross-tenant access and report persistence after service restart. It uses clearly marked synthetic test data and no model files. The initial test exposed an unreachable API port: an ingress network now permits the localhost-only published port while the database remains on its private network. Readiness checks tolerate bounded transient startup connection resets. The latest workflow result is authoritative; a supplied Compose file alone is not proof of deployment.

## Unfinished

Permanent public hosting is not provisioned. No paid service, subscription, trial or billing change was enabled. The complete generative model deployment, sustained inference load, browser/WebGL acceptance, independent scientific appraisal and operational monitoring remain unfinished. These improvements must not be represented as complete implementation of the master research design.
