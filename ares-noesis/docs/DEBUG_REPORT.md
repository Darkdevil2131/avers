> Archive documentation. See ENGINEERING_PROGRESS.md for the current verified state.

# Debug report (reproduce → isolate → diagnose → fix → prevent)

Every bug below was first reproduced by a failing test (or a benchmark), then root-caused, then fixed; the test stays as a regression guard.
Where a first fix was wrong, that is recorded too.

| # | Symptom (how reproduced) | Root cause | Fix | Guard |
|---|---|---|---|---|
| H1 | Retracted paper still returned by search | Index cache key was (count, max id); flipping `retracted` changed neither | key includes retracted count | `test_retraction_after_indexing…` |
| H2 | One task's DB error made every later task fail (`PendingRollbackError`); naive rollback would lose earlier work | shared session, no isolation between tasks | each task in a SAVEPOINT; SQLite SAVEPOINT support (documented pysqlite fix) | `test_failed_task_does_not_poison…` |
| H3 | 3 MB upload fully buffered before size check | `await file.read()` then compare | chunked read, 413 at limit | `test_oversize_upload…` |
| H4/H16 | unlimited expensive calls and password guesses | no throttling | sliding-window limiter (429 + Retry-After); stricter on login | `test_rate_limit…` |
| H7 | two concurrent analyses of one document corrupt claims | no active-job check | 409 with existing job id (stale `running` rows don't block) | `test_double_analyze…` |
| H8 | restore after a split silently produced a different belief | evidence moved to another belief was ignored | refuse with explanation | `test_restore_refuses…` |
| H11 | negative `k`, 600-char query accepted | no bounds | validated (1≤k≤50, 1≤len≤500) | `test_corpus_search_input_bounds` |
| H13 | page-bomb PDF fully extracted | no page cap | `max_pages` (400) | `test_pdf_page_bomb…` |
| H15 | login timing reveals which emails exist | hash skipped for unknown email | always verify (dummy hash) | `test_login_does_not_leak…` |
| H17 | table cell "5.19" extracted as `519\n.` | PyMuPDF cell text can scramble glyph order | rebuild cells from word boxes | `test_pdf_tables_extracted…` |
| H18 | LSA found nothing on tiny corpus | components ≈ doc count ⇒ no smoothing; my first fix (n/4) was still too many | ≈ n/12, capped | `test_lsa_retrieves_synonyms…` |
| H19 | consistent dimension check → HTTP 500 / MCP tool error | SymPy numbers (`One`) in the JSON result; direct-call unit tests passed, only the API path failed | plain ints + generic JSON normalisation on engine endpoint | `test_engine_results_are_always_json_serialisable…` |
| H20 | worker threads crashed with `database is locked` under 8 parallel workers (hidden: the test still passed) | SQLite refuses lock upgrades immediately, ignoring busy timeout; no retry | WAL + busy timeout + jittered retry around claim/schema; worker loop backs off instead of dying; claim made compare-and-set | `test_parallel_workers_never_double_claim`, stressed 15× |
| H21 | index: 10k docs = 35.6 s, 2.1 GB, 280 ms/query; 30k killed by OOM | all one-off bigrams kept in the vocabulary | min_df=2, 200k feature cap, float32, doc ceiling | `scripts/bench_index.py` (numbers in SYSTEM_DESIGN) |
| H22 | critic accepted a "revision" that dropped the hypothesis variables | substring match ("a" in "drifting") | whole-word match | `test_critic_loop_drops_revises_rejects_drift…` |
| H23 | LLM client wrapped inside another client; all LLM calls silently fell back | wrong constructor argument | pass instance through; per-document budget reset | `test_pipeline_with_llm_adds_grounded_claims…` |

**Lessons / prevention.** (1) Test through the API boundary, not only direct calls (H19). (2) A passing test can hide crashed threads (H20): the concurrency test now fails on any thread exception.
(3) Benchmark before trusting a design (H21). (4) Silent fallback paths need a recorded reason, otherwise breakage looks like "working but weak" (H23).
**Open, not fixed:** no lease heartbeat for >15-minute jobs; per-process rate limiter; index rebuild blocks queries; all external-API behaviour unverified live.
