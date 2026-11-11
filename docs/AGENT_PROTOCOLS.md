# Research protocol

Each run persists its question and whether external metadata search is permitted. Stages are plan, optional external_search_started/completed/failed, retrieve, audit, report. Events include run/project identity and ordered IDs. Clients read authenticated SSE and then fetch durable status/report; saved events can be replayed. Cancellation is checked between bounded operations. An in-flight network call can take up to its timeout to stop.

The worker claims queued or expired jobs transactionally, caps attempts at three, and commits final output atomically. No stage can invoke arbitrary tools or spend money. External failures are recorded and local retrieval continues. Reports always label scientific assessment inconclusive. Source content cannot alter stage instructions.

The policy coordinator can choose counterevidence queries from existing project evidence and broaden sparse searches. spider_fetch/document_ingested/document_rejected events describe actual API attempts. memory_retrieval records lexical/hybrid/reranker availability. Candidate extraction and critic events carry limitations. Optional local model inference is limited to 90 seconds and has no tools. Unsupported generated narratives are omitted from factual report summaries. Memory is written as pending, never immediately trusted.
