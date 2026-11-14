# Master design acceptance

The 31-page *ARES–Noesis Master Research and System Design* defines the scope. The table maps its sections to the current implementation and the evidence still needed for release. Automated assessments remain inconclusive pending scientific validation.

| Design area | Implementation | Release evidence still needed |
| --- | --- | --- |
| Executive and domain agents (pp. 8–12) | Bounded collection and counterevidence policy, persistent queue, task events and optional local proposals | Adaptive task graph with budgets and tool preconditions, domain-specific agents and falsification, comparisons with a static planner |
| RAG and source acquisition (pp. 12–13) | Lexical and dense retrieval, reranking, fixed Europe PMC/NCBI endpoints and license checks | Broader domain sources, scalable vector indexing, connector drift tests and measured coverage under a fixed budget |
| Document intelligence and provenance (pp. 12–15) | Exact text offsets, source hashes and stored structured full-text objects | PDF/OCR, tables and equations with location validation and isolated parser acceptance |
| Evidence assessment and independence (pp. 13–16, 20–22) | Reviewer-entered context, exact-span evidence links, source review history, shared study identifiers and bounded extraction of explicit exposure values | Expert-labeled context and stance validation, study-quality appraisal, underlying study/dataset/cohort identity and correction feeds |
| Reasoning, hypotheses and experiments (pp. 9–15) | Descriptive statistics, unit conversion, versioned proposals, review flags and a controlled comparison template for coating exposures | Capability-aware routing, validated statistics/causal/graph tools, prior-art search, broader domain experiment plans and expert review |
| Security and data (pp. 15–17, 20–22) | Authenticated project access, database row-level policies, source/run snapshots and disposable backup restoration | Production threat review, dependency checks, least-privilege worker review, production backup recovery and observability |
| Memory and reproducibility (pp. 2, 11, 17) | Pending memory, reviewed relevance feedback, recorded queries and report events | Frozen replay inputs and artifact versions, validation of feedback impact, poisoning evaluation and reproducible offline training if added |
| Interface (pp. 18–19) | React workflow view driven by recorded events, 3D collection/retrieval states and reduced-motion fallback | Desktop/mobile browser acceptance, full event-to-visual coverage and accessibility checks |
| Infrastructure and cost (pp. 22–24) | Container build and disposable PostgreSQL workflow checks | Verified live revision, no-trial hosting at ₹0 additional spend, durable storage, resource and inference-load measurements |
| Scientific and publication gates (pp. 24–28) | Small development-set retrieval/extraction comparisons and synthetic software regressions | Frozen materials-science test set, independent labels, baseline comparisons, ablations, error/abstention reporting and expert review |

## Reviewed study context in automated reports

The critic uses reviewer-entered context when both finding spans have active evidence links to the same claim. It compares the nine existing fields, preserves case-sensitive unit symbols and records the supporting review IDs. Missing context, differing fields and conflicting reviews are visible in reports and exports. The saved report preserves the comparison made during its run. New reviews can be evaluated by starting a new run.

This check uses exact span and field matching. It cannot infer context from an unread methods section, normalize equivalent scientific units, adjudicate reviewer disagreement or establish study independence. Opposing sentences remain review candidates. The next scientific acceptance test needs independently labeled same-context, context-mismatch and insufficient-information cases with a frozen scoring protocol.

## Reported exposure values

Finding text can supply explicit Celsius temperature, relative humidity, and exposure duration in hours or days. The extractor uses a narrow sentence-ending pattern for one stated test or conditioning stage. It records exact quotes and source offsets, converts days to hours for comparison, and skips unsupported or ambiguous wording. Each field is compared only when both findings supply a value. These comparisons do not establish equivalent materials, controls, outcomes, measurement protocols or study quality. The API regression uses synthetic coating observations, including differing temperatures and equivalent durations. Independent evaluation on published materials studies remains open.

The published wording development set in `benchmarks/materials_exposure.json` includes eight excerpts with section links and reviewer labels. Running the extractor from `ccf39da` on these excerpts recovered 0 of 14 labeled point values. The updated conditioning rules recover all 14 without emitting values for the three tolerance, range or multi-arm examples. These excerpts were selected to exercise the rule changes, so an independent sample is still needed to estimate error rates. Conditioning, exposure and testing values carry separate stage labels and are compared within the same stage only.

When two opposing coating findings report all three exposure values and exactly one differs, the hypothesis engine can draft a two-group comparison with references to both finding spans. This template skips shared study identifiers, conflicting reviews, and known mismatches in material, outcome, units or measurement. Proposed setpoints, controls and the outcome require review. The plan leaves sample size open until the equivalence margin, variance and power target are specified. This software behavior is tested with synthetic cases. Experiment validity and novelty still need independent review.
