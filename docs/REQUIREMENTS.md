# Requirements traceability

| Design requirement | Current implementation |
| --- | --- |
| No additional spending | No paid providers or provisioned services; bounded keyless metadata search |
| Project isolation | Named users, owner/editor/viewer authorization, scoped database queries |
| Provenance and evidence | Immutable source snapshots, hashes, offsets, licenses, reviews, cited reports |
| Retrieval | SQLite FTS5 lexical retrieval; semantic RAG remains pending |
| Bounded agents | Deterministic leased workflow, cancellation, three attempts; autonomous multi-agent reasoning pending |
| Scientific context | Reviewer-supplied nine-field fingerprints, mismatch/unknown handling |
| Hypotheses | Versioned proposals with mechanism and falsification criteria |
| Tool execution | Audited sample statistics and unit conversion; no arbitrary code |
| Memory | Persistent project sources/reports/claims/history; learning is not implemented |
| React and 3D | Source graph, progress, reports, source review, claim and hypothesis forms |
| Operations | SQL schema scripts, backup verification, hosted-shell and Docker recipes |
| Quality gates | Backend behavior tests, frontend interaction tests, production build |

The master design remains the target. Features listed as pending are not represented as complete.
