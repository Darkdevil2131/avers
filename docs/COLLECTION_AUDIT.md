# Bounded source collection audit

Europe PMC's existing search endpoint returns publication metadata. The collector separately requests full text and accepts only its supported reusable licences. The integration uses the fixed Europe PMC/NCBI endpoints without a paid search or inference API. API reference: https://europepmc.org/RestfulWebService

Every new research report now stores a collection audit in its JSON, displays it in the workspace and includes it in Markdown exports. Earlier reports are preserved without retroactively inventing an audit.

| Status | Meaning |
| --- | --- |
| not_requested | Run used stored project evidence; external collection was disabled |
| no_results | The bounded metadata search returned no usable records |
| metadata_only | Metadata was found, but no full text was stored |
| collected | Full text was stored within the bounded search; not an exhaustive literature review |
| partial | Some results were retained, but a request failed or a collection bound was reached |
| unavailable | Collection failed without usable metadata results |

The audit retains queries and strategies, deduplicated metadata count, attempted/stored full-text counts, bounded-collection flag and failures. A failed broadening request no longer discards the useful first search. Full-text licence failures remain visible; project RAG continues with available evidence. Metadata titles do not become extracted scientific findings. Missing results never establish that a hypothesis is false.

Malformed primary result schemas use the existing approved NCBI fallback. Invalid queries, result limits and PMC identifiers are rejected. Cached results are copied so a caller's broadening/edits cannot corrupt later searches. Collection remains bounded to two searches, two initial PMC candidates, four full-text attempts and reference depth one; no claim of exhaustive search or automatic scientific validation is made.

Tests cover malformed schemas, cached-result mutation, rejected input, preserved results after broadening failure, deduplication, licence rejection, saved/exported failure status, local-only runs and empty searches. The React test verifies failure status is visible in the report. Mock fixtures test failure behavior; they are not live scientific evidence.
