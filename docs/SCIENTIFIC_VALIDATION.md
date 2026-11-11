# Scientific validation

Retrieval is an information-finding operation. Every report is explicitly inconclusive and uncalibrated. A report citation must match the exact stored substring and includes source SHA-256, offsets, retrieval timestamp, licensing metadata, and source review version. Later retractions flag old reports as outdated and exclude sources from new retrieval.

Claim assessments summarize reviewer-entered supports/contradicts/neutral relationships. Nine fields are compared: subject, variable, units, population/material, conditions, study design, outcome, measurement, and timeframe. Comparison is normalized exact text equality, not semantic reasoning. Any mismatch prevents that link from contributing; unknown fields remain unverified. Study identifier grouping is shown, but study independence is not established. Labels such as supported or mixed are not probabilities or claims of scientific truth.

Hypotheses are proposals with mechanism and falsification text, not executed experiments. Tool results are actual deterministic calculations on submitted data. No experimental results, paper contents, confidence probabilities, or validated benchmarks are fabricated.

Tests cover exact offsets, retraction propagation, context mismatch, unknown context, mixed reviewer evidence, preserved hypothesis versions, injected source instructions, and numeric tool reference values. Automated causal inference and domain-expert validation have not been established.

Release 0.3 adds a ten-case synthetic paraphrase smoke evaluation, real local model integration, and safe XML/citation traversal tests. These are not domain benchmarks. An observed model hallucination is preserved in local-model-failure-observed.json. The revised narrative gate accepts only exact source extracts for factual answer text. Model-generated hypotheses remain speculative and unvalidated; their presence does not mean the model has established a valid mechanism or correctly designed a falsification experiment.

## Recorded SciFact development evaluation

The committed script evaluates 27 development claims whose gold documents fall within a fixed-seed 1,000-document corpus (2,081 passages). Gold is used for selection and scoring, not retrieval. Both lexical and hybrid recall@8 are 1.0 on this restricted corpus. With sentence reranking, 18/27 first candidates match an annotated rationale; precision across all extracted candidates is 0.3333. All 27 queries used hybrid retrieval and reranking. Full per-claim results are in scifact-evaluation.json.

Earlier results are retained: scifact-capacity-baseline.json hit the old dense limit and actually used lexical retrieval, despite the aggregate metric name; scifact-extraction-baseline.json used hybrid retrieval but had about 9.85% candidate precision. Extraction selection was changed after observing these results. This is development evaluation, not an untouched acceptance set, full-corpus benchmark, or validation of hypothesis mechanisms. Rationale matching uses sentence containment rather than semantic equivalence.

The initially interrupted second evaluation was rerun successfully on 2026-11-11. Its saved result is described below. No scientific production approval is implied by passing software CI.

## Distinct-claim follow-up

scifact-independent-check.json records an unchanged-pipeline rerun using document seed 20261112 and excluding all 27 earlier claim IDs. There are 30 different claims, 1,000 corpus documents and 2,074 passages. Lexical recall@8 is 90.0%; hybrid recall@8 is 96.7% (29/30). First-candidate rationale agreement is 63.3% (19/30), and candidate rationale precision is 36.7%. All 30 queries used real dense retrieval and reranking. The run took 251.6 seconds on the hosted CPU.

The filename does not imply an independent scientific audit: both samples come from the published development split and may share corpus documents. The pipeline was not adjusted between the first and follow-up runs. This is a check on distinct claims, not the hidden official test set, full-corpus retrieval, causal verification, or expert assessment. The new result confirms that relevant document retrieval does not ensure correct evidence selection. Scientific production acceptance remains unmet.

Reproduce after explicit model preparation:

```bash
ARES_EVAL_SEED=20261112 ARES_EVAL_EXCLUDE=docs/scifact-evaluation.json ARES_EVAL_OUTPUT=docs/scifact-independent-check.json PYTHONPATH=. python scripts/evaluate_scifact.py
```
