# Cost and infrastructure

Hard constraint: ₹0 additional external spending. No paid API, billing account, card, trial, hosted database subscription, LLM endpoint, or paid compute provisioning is configured. Development and tests run in the existing hosted Work environment. The user's browser still uses some local memory to display the interface; build and backend test workloads run remotely.

The only external research adapter uses the keyless Europe PMC API. Europe PMC's team states that this API is free: https://groups.google.com/a/ebi.ac.uk/g/epmc-webservices/c/cZLnV1JhCj8 . Only bibliographic metadata is imported automatically; article copyrights require separate review. The adapter makes at most one request per second per process, caches responses for five minutes, limits results to ten and responses to 2 MB, and times out after 15 seconds. Failures are visible; there is no paid fallback.

GitHub verification uses a standard runner only when the repository is public, with a ten-minute job timeout and no artifact upload or cache storage. Private repositories skip that job. No hosted deployment is enabled by the workflow. Future service terms can change; the code cannot guarantee unlimited free hosting. Do not provision external services under the present constraint.

The Work environment is temporary. An always-on public service and durable external storage have not been provisioned. Docker and shell instructions are packaging options for an already available host, not authorization to rent one.
