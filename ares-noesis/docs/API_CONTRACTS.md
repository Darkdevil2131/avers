# API contracts

| Route | Contract |
| --- | --- |
| `GET /health` | Public liveness response |
| `POST /api/v1/projects` | Creates a project under the authenticated account in users mode |
| `POST /api/v1/projects/{pid}/documents` | Stores a bounded upload and returns document ID, digest and duplicate status |
| `POST /api/v1/projects/{pid}/documents/{did}/analyze` | Queues document analysis for a document in that project |
| `POST /api/v1/projects/{pid}/query` | Queues research for a bounded question |
| `GET /api/v1/jobs/{jid}` | Project-scoped job status and results |
| `GET /api/v1/projects/{pid}/report` | Latest project report; reports from individual jobs carry a job ID internally |
| `GET /api/v1/projects/{pid}/beliefs` | Project-scoped belief assessments and evidence references |

The generated OpenAPI schema describes the remaining endpoints. Cross-project requests from researchers return 404. Shared-corpus write operations and direct engine calls are restricted to administrators in accounts mode.
