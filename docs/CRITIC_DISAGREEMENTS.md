# Cross-source disagreement review

The evidence critic previously checked related sentences for different negation
but missed explicit increase/decrease pairs without negation. It now uses the
existing conservative direction check, subject to the existing word-overlap
threshold, to flag potential opposing directions across source snapshots.

Each flag retains both exact finding statements and citation labels, exposes
shared study identifiers, and asks reviewers to compare outcome/units,
population/material, exposure/comparator/timeframe, uncertainty/design and
independent study identity. The React report and Markdown export show these
details. Matching identifiers warn against treating reports as independent;
different identifiers do not establish independence.

The critic still abstains from scientific verdicts. It cannot resolve synonymy,
causality, contextual equivalence or significance from word overlap. A flag is
a review lead, not proof of contradiction, fabrication or falsity. Same-source
internal inconsistencies remain outside this cross-source check.

Validation: 99 backend tests passed locally (3 PostgreSQL checks require CI).
Five new synthetic cases cover opposing directions, unrelated/matching results,
shared identifiers, negation and same-source boundaries. No new benchmark
accuracy or expert scientific validation is claimed. No paid services, trials
or deployment changes are included.
