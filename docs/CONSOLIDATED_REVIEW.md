# Combined changes and repository review — 2026-11-13

Reviewed main at `a1d010129ad40c053cd7e6f98af4475199edba0d` and all
remaining open PRs (#10, #11, #13). PRs #12 and #14 had already been merged
into intermediate branches, not main. This consolidated change includes their
code and preserves the existing main tree and branch histories.

## Included work

- Reconnect interrupted research streams and prevent stale report replacement.
- Preserve metadata when a broadening search fails; record collection coverage,
  bounds, query strategies and source failures in reports.
- Bound local model output and explicitly reject incomplete or invalid JSON.
- Retain both failed and successful real-model queue measurements.
- Handle negated direction words conservatively and expose review limits in UI.
- Correct an additional scan finding: low-overlap statements require review,
  rather than displaying a clear direction check for unrelated outcomes.

## Review scope

Inspected the combined source diff, commit ancestry, provider handling,
reasoner validation, critic status, React report/reconnect behavior, CI and
Compose configuration. Checked for obvious dynamic execution, disabled TLS
verification and credential-handling patterns. This was a focused code review,
not a penetration test or a guarantee that all defects have been found.

The merge of current main and the latest critic/UI branch is conflict-free.
The collection branch's merge of #12 adds no different file content from its
already-included inference commit. No pending branch content is discarded.

Existing CI exercises backend/UI tests, PostgreSQL isolation and restoration,
30-user API load, queued Compose persistence, live full-text provenance and
container startup. The API load test does not measure model inference capacity.
The final combined PR's checks are the authoritative result for this revision.

No deployment, paid API, billing or trial configuration is changed. Outstanding
limitations remain scientific evaluation, browser/WebGL acceptance, sustained
model-inference load and verification of a live host satisfying the zero-cost
requirement. This consolidation is not a production-readiness declaration.
