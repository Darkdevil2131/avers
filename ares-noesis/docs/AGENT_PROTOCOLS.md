# Agent protocols

The prototype passes Python task objects through a deterministic DAG and stores outcomes and status in the job result. Source adapters and tool dispatch are application functions. The MCP server calls the same authenticated API. Its credentials inherit the same API permissions.

The research sheet calls for explicit objective, dependencies, evidence snapshot, tool allowlist, schemas, deadline, retry budget and stop reason on every task. Implement that contract before extending the Research Executive or adding new live capabilities.
