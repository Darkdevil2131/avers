# Critic context regression checks — 2026-11-13

The deterministic proposal critic previously interpreted `did not increase` as
an increase, and mixed exposure adjectives such as `lower humidity` into the
outcome direction. This could both reject compatible statements and miss an
explicit increase/decrease conflict.

Negation now produces `requires_review`, without inferring an opposite effect.
Explicit increase/decrease verbs take precedence over comparative adjectives;
bare higher/lower adjectives do not establish an outcome direction. Mixed
directions also require review. Explicit mechanism disclaimers still reject a
candidate. Reports retain the direction-check reason and disclose that context
is not verified. `accepted_as_candidate` means only that these rules did not
reject it; `scientific_validation` remains false.

Validation in the cloud workspace: 80 backend tests passed, 3 PostgreSQL tests
skipped because this run had no configured PostgreSQL test database. Eleven new
synthetic regression cases cover negation, exposure comparatives, predicative
comparisons, mixed outcomes and mechanism disclaimers.

These cases are not an independent scientific benchmark. The critic still does
not align outcomes, populations, experimental conditions or causal claims.
Broad negation conservatively defers some cases that could be resolved with
semantic analysis. Lexical overlap is not proof of matching scientific context.
No new SciFact accuracy result or production readiness is claimed. No hosting,
billing, paid API or trial configuration was changed.
