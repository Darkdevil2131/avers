CREATE TABLE IF NOT EXISTS memberships(
 project_id TEXT NOT NULL REFERENCES projects(id), username TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('owner','editor','viewer')),
 PRIMARY KEY(project_id,username));
INSERT OR IGNORE INTO memberships SELECT id,owner,'owner' FROM projects;
CREATE TABLE IF NOT EXISTS source_details(
 source_id TEXT PRIMARY KEY REFERENCES sources(id), title TEXT NOT NULL,
 study_id TEXT NOT NULL, origin TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_reviews(
 id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL REFERENCES sources(id),
 status TEXT NOT NULL CHECK(status IN ('active','retracted','excluded')),
 reason TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS passages(
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
 project_id TEXT NOT NULL REFERENCES projects(id), start_offset INTEGER NOT NULL,
 end_offset INTEGER NOT NULL, text TEXT NOT NULL,
 UNIQUE(source_id,start_offset));
CREATE VIRTUAL TABLE IF NOT EXISTS passage_search USING fts5(
 passage_id UNINDEXED, project_id UNINDEXED, text, tokenize='unicode61');
CREATE TABLE IF NOT EXISTS run_state(
 run_id TEXT PRIMARY KEY REFERENCES runs(id), status TEXT NOT NULL
 CHECK(status IN ('queued','running','completed','failed','cancelled')),
 external INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
 lease_until REAL NOT NULL DEFAULT 0, cancelled INTEGER NOT NULL DEFAULT 0,
 error TEXT, request_key TEXT, project_id TEXT NOT NULL REFERENCES projects(id),
 UNIQUE(project_id,request_key));
INSERT OR IGNORE INTO run_state(run_id,status,project_id) SELECT id,'queued',project_id FROM runs;
CREATE TABLE IF NOT EXISTS run_events(
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
 stage TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reports(
 run_id TEXT PRIMARY KEY REFERENCES runs(id), payload TEXT NOT NULL,
 markdown TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_events(
 id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT REFERENCES projects(id),
 actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS reports_no_update BEFORE UPDATE ON reports
 BEGIN SELECT RAISE(ABORT,'reports are immutable'); END;
CREATE TRIGGER IF NOT EXISTS reports_no_delete BEFORE DELETE ON reports
 BEGIN SELECT RAISE(ABORT,'reports are immutable'); END;
CREATE TRIGGER IF NOT EXISTS reviews_no_update BEFORE UPDATE ON source_reviews
 BEGIN SELECT RAISE(ABORT,'reviews are append-only'); END;
CREATE TRIGGER IF NOT EXISTS reviews_no_delete BEFORE DELETE ON source_reviews
 BEGIN SELECT RAISE(ABORT,'reviews are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON run_events
 BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON run_events
 BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
INSERT OR IGNORE INTO schema_versions VALUES(2);
