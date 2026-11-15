# Master design acceptance

The 31-page *ARES–Noesis Master Research and System Design* defines the scope. The table maps its sections to the current implementation and the evidence still needed for release. Unreviewed findings continue to receive an inconclusive assessment. Claim-linked runs can summarize explicitly recorded reviewer judgments.

To use this workflow, record a claim and evidence links in **Evidence review**, then select **Research this claim**. The report saves the eligible and excluded links together with their review IDs and source spans. A new review or source retraction flags older reports as stale. If there are more than 100 links, the report shows the first 100 and abstains. For PostgreSQL, apply the normal administrative migration before starting the updated API and worker.

Use **Add a source → Upload a PDF** to attach a document you have permission to store. You can enter a DOI or study ID to group it with existing sources that use the same identifier. **Source library → Download original PDF** returns the saved file after checking its SHA-256 hash. **Evidence report → Download PDF** exports the report, including any stale-source warnings. The Markdown download remains available. Uploaded PDFs are limited to 2 MB and 40 pages. English OCR runs on up to eight pages without a text layer. Citations identify physical PDF pages and whether the text came from OCR or the PDF text layer. Newly uploaded text-layer PDFs can expose captioned, consistently aligned table candidates through **Download structured source**. Cell offsets refer to the extracted source text. Review the original page before using a table. Multi-line or merged cells, scanned tables and other layouts need further work.

| Design area | Implementation | Release evidence still needed |
| --- | --- | --- |
| Executive and domain agents (pp. 8–12) | The planner can broaden thin retrieval or search for counterevidence after opposing findings. Reports preserve its decisions and before/after candidate coverage. | Domain-specific task routing and falsification, independent comparisons with a static planner |
| RAG and source acquisition (pp. 12–13) | Lexical and dense retrieval, reranking, fixed Europe PMC/NCBI endpoints and license checks | Broader domain sources, scalable vector indexing, connector drift tests and measured coverage under a fixed budget |
| Document intelligence and provenance (pp. 12–15) | PDF text extraction, bounded English OCR, page-linked citations, original document and report downloads, structured rows from explicit HTML-style JATS tables, and captioned aligned PDF table candidates with cell offsets | Validation on diverse PDF table layouts, equations and scanned tables, multilingual OCR, and stronger parser isolation |
| Evidence assessment and independence (pp. 13–16, 20–22) | Claim-linked runs snapshot reviewer-entered support or opposition with exact spans, exclusions, and study identifier groups. The planner, critic, and prior-art screen group recognized variants of DOIs, PMCIDs, and explicitly entered NCT IDs. The critic also compares reviewed fields and explicit exposure values. | Expert-labeled context and stance validation, study-quality appraisal, links between publications with different identifiers that reuse a dataset or cohort, and correction feeds |
| Reasoning, hypotheses and experiments (pp. 9–15) | Descriptive statistics, unit conversion, versioned proposals, review flags, bounded literature title screening with an optional dedicated topic search, and a controlled comparison template for coating exposures | Measured screening recall and expert novelty and experiment review, capability-aware routing, validated statistics/causal/graph tools, broader domain experiment plans |
| Security and data (pp. 15–17, 20–22) | Authenticated project access, database row-level policies, source/run snapshots and disposable backup restoration | Production threat review, dependency checks, least-privilege worker review, production backup recovery and observability |
| Memory and reproducibility (pp. 2, 11, 17) | Pending memory, reviewed relevance feedback, recorded queries, and offline Markdown reconstruction from immutable reports with verified cited source snapshots | Frozen-corpus retrieval and inference replay, model artifact versions, validation of feedback impact, poisoning evaluation and reproducible offline training if added |
| Interface (pp. 18–19) | React workflow view driven by recorded events, 3D collection/retrieval states, reduced-motion fallback, and a Chromium check of the disposable Compose stack and report downloads | Production desktop/mobile browser acceptance, full event-to-visual coverage and accessibility checks |
| Infrastructure and cost (pp. 22–24) | Container build and disposable PostgreSQL workflow checks | Verified live revision, no-trial hosting at ₹0 additional spend, durable storage, resource and inference-load measurements |
| Scientific and publication gates (pp. 24–28) | Small development-set retrieval/extraction comparisons and synthetic software regressions | Frozen materials-science test set, independent labels, baseline comparisons, ablations, error/abstention reporting and expert review |

For a full-text failure, new collection reports identify the PMC article and show
sanitized outcomes for both providers, such as a timeout, missing article, or
unsupported license. A successful NCBI BioC fallback preserves the primary
failure category in the structured document. Historical reports retain their
original error details.

## Literature screening, table export and historical replay

**Download replay bundle** saves the historical report, its cited source text,
and recorded settings. Treat it as private research data. Run
`python -m ares.replay ares-replay.json restored-report.md` to verify source
hashes, citation and finding spans and reconstruct the saved Markdown offline.
Add `--check-findings` to rerun extraction over the archived cited passages with
the currently installed local models and compare ordered findings and methods.
New reports record a digest of the local reranker snapshot, including model and
tokenizer files, which the comparison checks. Older reports lack that digest and
show model identity as unverified. The command prints both selections and exits
with an error if they differ or the recorded snapshot differs. The ordinary report
download adds current retraction and review notices. Retrieval, external search,
and hypothesis inference are not rerun by the historical reconstruction.

Before publishing a proposal, the worker screens available literature titles. If
external collection was requested and a search slot remains, the worker also
queries for up to three terms from the submitted question. The two-search budget
is shared with adaptive evidence collection. The report records the query, the
number of titles returned and skipped or failed searches. Proposal text, project
findings and citations stay local. Topic matches flag possible overlap for review.
Novelty remains unverified. Newly collected Europe PMC JATS
records expose bounded rows, header flags and supplied span attributes through
**Download structured source**. Previously stored document snapshots are unchanged.

## Reviewed study context in automated reports

The critic uses reviewer-entered context when both finding spans have active evidence links to the same claim. It compares the nine existing fields, preserves case-sensitive unit symbols and records the supporting review IDs. Missing context, differing fields and conflicting reviews are visible in reports and exports. The saved report preserves the comparison made during its run. New reviews can be evaluated by starting a new run.

This check uses exact span and field matching. It cannot infer context from an unread methods section, normalize equivalent scientific units, adjudicate reviewer disagreement or establish study independence. Opposing sentences remain review candidates. The next scientific acceptance test needs independently labeled same-context, context-mismatch and insufficient-information cases with a frozen scoring protocol.

## Reported exposure values

Finding text can supply explicit Celsius temperature, relative humidity, and exposure duration in hours or days. The extractor uses a narrow sentence-ending pattern for one stated test or conditioning stage. It records exact quotes and source offsets, converts days to hours for comparison, and skips unsupported or ambiguous wording. Each field is compared only when both findings supply a value. These comparisons do not establish equivalent materials, controls, outcomes, measurement protocols or study quality. The API regression uses synthetic coating observations, including differing temperatures and equivalent durations. Independent evaluation on published materials studies remains open.

The published wording development set in `benchmarks/materials_exposure.json` includes eight excerpts with section links and reviewer labels. Running the extractor from `ccf39da` on these excerpts recovered 0 of 14 labeled point values. The updated conditioning rules recover all 14 without emitting values for the three tolerance, range or multi-arm examples. These excerpts were selected to exercise the rule changes, so an independent sample is still needed to estimate error rates. Conditioning, exposure and testing values carry separate stage labels and are compared within the same stage only.

When two opposing coating findings report all three exposure values and exactly one differs, the hypothesis engine can draft a two-group comparison with references to both finding spans. This template skips shared study identifiers, conflicting reviews, and known mismatches in material, outcome, units or measurement. Proposed setpoints, controls and the outcome require review. The plan leaves sample size open until the equivalence margin, variance and power target are specified. This software behavior is tested with synthetic cases. Experiment validity and novelty still need independent review.
