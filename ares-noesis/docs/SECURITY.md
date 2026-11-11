# Security

The API fails before opening the database if the selected authentication mode lacks a suitable key. In account mode, initial administrator registration requires the configured API key. Ordinary registration defaults to closed. API-key mode grants a single operator full access and is intended for private development. Account mode scopes researcher reads and writes by project owner and grants administrators broader access. Shared corpus sync and direct engine calls require an administrator.

Server-owned identifiers and hashes determine upload storage paths. File size and page count checks supplement parsing. The current multipart parser can spool requests before handler checks and PDF parsing runs inside the app process. Use trusted test inputs on a private bind until ingress limits and parser isolation are implemented. Connectors use code-owned endpoints and the default HTTP transport rejects redirects. A future crawler requires destination validation and independent egress controls.

Open gates include PostgreSQL RLS, upload isolation, engine resource limits, revocable sessions, abuse controls across replicas, audit redaction review, dependency scanning and restore testing. The public GitHub branch contains code and synthetic fixtures. Application data and credentials belong in the hosted runtime.
