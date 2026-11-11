# Requirements traceability

| Requirement | Implemented behavior | Remaining gap |
| --- | --- | --- |
| No additional spending | No billable endpoints/trials/provisioning; local inference on existing host | Always-on free hosting not established |
| Project security | Named users, scoped owner/editor/viewer authorization, input/source budgets, PostgreSQL RLS | Public ingress controls, scale tests |
| Lawful collection | Fixed API, explicit license gate, safe XML/BioC, depth/document bounds, live provenance checks | Broader sources/PDF |
| RAG | Real MiniLM embeddings + FTS + RRF + cross-encoder; local Qwen generation | Independent final scientific acceptance and robust synthesis |
| Agents | Policies choose primary/counterevidence search and broaden sparse searches; extraction/critic/generation stages emit events | Adaptive domain reasoning and independent critic validation |
| Evidence | Exact quotes, hashes, location offsets, extracted candidate statements, reviewer context, retraction history | Automated validated study appraisal and independence analysis |
| Hypotheses | Local model generates cited mechanism/falsification candidates; deterministic replication fallback | Validated plausibility, prior-art search, expert assessment |
| Learning | Per-run pending memory, owner review, relevance feedback used in similar-query embeddings | Evaluated learning gains and offline model training |
| Tools | Sample statistics and dimension-checked units | Domain reasoning and experimental design tools |
| UI | React, actual-event spider/DB activity visuals, reports, sources, evidence forms | Browser visual/WebGL validation and production UX review |
| Operations | Locks, leases, limits, backup verification, CI, tested Docker build/start, PostgreSQL RLS | Production deployment and recovery/load objectives |
