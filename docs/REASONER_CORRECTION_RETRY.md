# Bounded correction after a critic rejection

The worker limits the first local model call to 90 seconds and the correction to 30 seconds. It also caps each call at the remaining research time minus one second and requires at least two seconds of remaining time. Both calls require an active run lease. A timeout is reported without the executable or model path.

The worker considers one correction when the local model produces no accepted candidate and the critic flags a potential direction opposition. The model loads again for that call, which can increase latency and compute use.

The retry instruction is a fixed system instruction describing the critic's concern; model-generated text is not used as an instruction. The same source-quote checks and critic are applied to the second candidate. Both rejected candidates, when present, remain in the critique; if no candidate passes, the existing replication fallback is used. Reports record the initial attempt and retry status, and the workspace and Markdown export disclose that a correction was attempted. A completed call or a candidate passing the rules does not establish correctness.

The tests in `test_reasoner_retry.py` use a mocked model and synthetic source. They exercise success, repeated rejection, failure and the no-retry path; they do not measure actual model improvement. The previous local-model test rejected all nine candidates in one synthetic scenario. The model and inference runtime were unavailable for a new run when this change was made, so whether the retry improves that result is **unknown**. Independent expert evaluation, broader model testing, live deployment verification and a verified no-trial ₹0 host remain open.
