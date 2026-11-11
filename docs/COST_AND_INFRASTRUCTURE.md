# Cost and infrastructure

Hard constraint: ₹0 additional external spending. No paid API, billing account, card, trial, hosted database subscription, LLM endpoint, or paid compute provisioning is configured. Development and tests run in the existing hosted Work environment. The user's browser still uses some local memory to display the interface; build and backend test workloads run remotely.

External research adapters use keyless Europe PMC and approved NCBI metadata/BioC APIs. Europe PMC's team states that this API is free: https://groups.google.com/a/ebi.ac.uk/g/epmc-webservices/c/cZLnV1JhCj8 . Bibliographic metadata is imported; full text is accepted only under explicitly recognized reuse licenses. The adapter makes at most one request per second per process, caches responses for five minutes, limits search results to ten and search responses to 2 MB; XML responses are capped at 4 MB, with a 15-second Europe PMC timeout and 20-second NCBI fallback timeout. Failures are visible; there is no paid fallback.

GitHub verification uses a standard runner only when the repository is public, with a ten-minute job timeout and no artifact upload or cache storage. Private repositories skip that job. No hosted deployment is enabled by the workflow. Future service terms can change; the code cannot guarantee unlimited free hosting. Do not provision external services under the present constraint.

The Work environment is temporary. An always-on public service and durable external storage have not been provisioned. Docker and shell instructions are packaging options for an already available host, not authorization to rent one.

Optional inference runs entirely in the existing host using openly licensed downloaded MiniLM, cross-encoder and Qwen weights. No paid inference endpoint exists. CPU/RAM/storage are still required on that host; an always-on no-billing host has not been secured or provisioned.

## Hosting feasibility checked 2026-11-11

No compatible permanent no-charge host is connected. Render and Railway integrations are available but unconnected; connecting one alone would not establish adequate free capacity. No provider account was created.

- Render's free web service has 512 MB RAM, ephemeral storage, and idle suspension. Free PostgreSQL expires after 30 days. Its documentation explicitly excludes production use of free instances. This cannot provide this system's durable full-model deployment as specified. https://render.com/docs/free and https://render.com/pricing
- Railway's Free resource limit is 0.5 GB RAM; new account signup starts a trial. The trial is prohibited by this project's requirement. https://docs.railway.com/pricing/plans and https://docs.railway.com/pricing/free-trial
- Hugging Face CPU Basic has no hourly hardware fee, but creating Docker/Gradio compute Spaces requires a paid subscription. It is not a zero-additional-cost deployment route here. https://huggingface.co/docs/hub/spaces-overview

Do not substitute an expiring database, a paid subscription labeled free hardware, or a static frontend for a complete hosted product. An existing authorized cloud machine with adequate model capacity and durable storage, provided at no additional charge, is needed before actual deployment can proceed. Provider terms can change; none of these checks guarantees permanent pricing.
