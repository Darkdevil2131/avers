# Scientific validation

Retrieval is an information-finding operation. Every report is explicitly inconclusive and uncalibrated. A report citation must match the exact stored substring and includes source SHA-256, offsets, retrieval timestamp, licensing metadata, and source review version. Later retractions flag old reports as outdated and exclude sources from new retrieval.

Claim assessments summarize reviewer-entered supports/contradicts/neutral relationships. Nine fields are compared: subject, variable, units, population/material, conditions, study design, outcome, measurement, and timeframe. Comparison is normalized exact text equality, not semantic reasoning. Any mismatch prevents that link from contributing; unknown fields remain unverified. Study identifier grouping is shown, but study independence is not established. Labels such as supported or mixed are not probabilities or claims of scientific truth.

Hypotheses are proposals with mechanism and falsification text, not executed experiments. Tool results are actual deterministic calculations on submitted data. No experimental results, paper contents, confidence probabilities, or validated benchmarks are fabricated.

Tests cover exact offsets, retraction propagation, context mismatch, unknown context, mixed reviewer evidence, preserved hypothesis versions, injected source instructions, and numeric tool reference values. No scientific benchmark accuracy, automated causal inference, or domain-expert validation has been established.

Release 0.3 adds a ten-case synthetic paraphrase smoke evaluation, real local model integration, and safe XML/citation traversal tests. These are not domain benchmarks. An observed model hallucination is preserved in local-model-failure-observed.json. The revised narrative gate accepts only exact source extracts for factual answer text. Model-generated hypotheses remain speculative and unvalidated; their presence does not mean the model has established a valid mechanism or correctly designed a falsification experiment.
