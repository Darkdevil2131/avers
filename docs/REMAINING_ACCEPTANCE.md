# Remaining acceptance work — 2026-11-14

Main at 749aa207 includes PRs #15 and #16. Passing software checks does not
establish completion of the autonomous research design.

| Area | Remaining work | Completion evidence needed |
| --- | --- | --- |
| Scientific selection | Restore benchmark/model artifacts; evaluate broader untouched claims; inspect wrong selections and precision regressions | Reproducible per-claim outputs, held-out evaluation and independent scientific review |
| Scientific interpretation | Align populations/materials, intervention/exposure, outcome, conditions and uncertainty; validate contradictions | Expert-labelled context and contradiction cases; reported false positives and abstentions |
| Inference capacity | Restore pinned model files and bindings; exercise repeated multi-user inference with queue limits, cancellation and restart | Measured successes/failures, latency and resource use over sustained load, including PostgreSQL |
| Browser acceptance | Exercise login, research events, 3D/2D views, cancellation, source review and exports in an accessible browser environment | Actual browser observations; component tests alone are insufficient |
| Live deployment | Inspect the current deployed commit, API/worker services, secrets configuration, HTTPS, volumes and backup restoration | End-to-end results on the actual authorized host, with isolation checks |
| Zero-cost condition | Verify the actual host account/plan, usage and deployment triggers; no trials or paid services | Current account-specific evidence of no charge; no promise of indefinite free capacity |
| Full research design | General source coverage, reliable study-context reasoning and expert-approved learning remain incomplete | Explicit requirement-by-requirement acceptance against the research design |

The existing 30-user test is API/queue load, not 30-user model inference.
The earlier real-model run covered three jobs only. Current first-selection
results on small development sets do not establish scientific reliability.
RAG remains; approved memory and relevance feedback do not train model weights.

Current session found an additional export-integrity gap: saved Markdown lacked
the live stale-source warning and model/proposal review details. Read-time exports
now add those disclosures, including for older stored reports, without rewriting
the historical report. Validation: 94 backend tests passed, 3 PostgreSQL tests
require CI. Tests include downloading after retraction, unchanged stored data,
legacy report handling and explicit model rejection/proposal disclosures.

No deployment or billing configuration was changed. No paid API or trial was
enabled. The temporary workspace no longer contains prepared model weights or
the evaluation dataset; restore these before claiming a new measured model run.
