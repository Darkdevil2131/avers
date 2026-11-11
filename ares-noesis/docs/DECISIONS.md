# Decisions

- Use the attached noesis_9 archive as the baseline. It contains more working code than the earlier prototype analyzed in the master design.
- Use SQLite and workspace blob storage for this private build. PostgreSQL and row-level security remain release gates.
- Default to offline operation and require authentication before startup. Retain provider adapters for isolated tests and later verification.
- Preserve prior hypothesis rows and link new outputs to their producing jobs. Legacy rows can have no job ID.
