CREATE TABLE IF NOT EXISTS worker_status (
    worker_id TEXT PRIMARY KEY,
    last_seen DOUBLE PRECISION NOT NULL,
    reasoning_status TEXT NOT NULL
);
INSERT OR IGNORE INTO schema_versions(version) VALUES(7);
