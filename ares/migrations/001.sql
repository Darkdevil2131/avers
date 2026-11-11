
CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_versions VALUES(1);
CREATE TABLE IF NOT EXISTS projects(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 question TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 url TEXT NOT NULL, text TEXT NOT NULL, digest TEXT NOT NULL,
 license_status TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(project_id, url, digest, license_status));
CREATE TRIGGER IF NOT EXISTS sources_immutable_update BEFORE UPDATE ON sources
 BEGIN SELECT RAISE(ABORT, 'source snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS sources_immutable_delete BEFORE DELETE ON sources
 BEGIN SELECT RAISE(ABORT, 'source snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS runs_immutable_update BEFORE UPDATE ON runs
 BEGIN SELECT RAISE(ABORT, 'research runs are immutable'); END;
CREATE TRIGGER IF NOT EXISTS runs_immutable_delete BEFORE DELETE ON runs
 BEGIN SELECT RAISE(ABORT, 'research runs are immutable'); END;
