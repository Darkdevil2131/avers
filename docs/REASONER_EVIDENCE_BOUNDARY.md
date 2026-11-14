# Reasoner evidence boundary review

Reviewed main commit `d4b10b87b2224ca3cee0d65ba90b8fe92c707a3a` on
2026-11-14. It contains the consolidated changes from PR #15.

The model receives at most three substantive citations, each truncated to 900
characters. Previously the returned quote was checked against all retrieved
citations and their complete text. A proposal could therefore pass validation
using metadata, a fourth citation or text outside the actual supplied context.
Validation now requires the citation and quote to match the evidence sent to
the model. Published extract answers obey the same boundary. A non-object
response envelope or proposal is rejected explicitly.

Cloud-workspace backend validation: 92 tests passed; 3 PostgreSQL tests were
skipped locally and require the CI database. Eleven new cases use mocked
inference to exercise invalid envelopes/proposals, excluded metadata, an unseen
fourth citation, text beyond the supplied excerpt, and a valid quoted candidate.
These are software boundary tests, not a live-model or scientific benchmark.

Exact quoting verifies provenance only. Hypotheses remain unvalidated;
scientific accuracy, full browser acceptance, sustained inference capacity and
zero-cost production hosting are still unresolved. No deployment, paid service,
billing or trial setting was changed.
