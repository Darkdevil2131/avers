CREATE TABLE IF NOT EXISTS claims(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 statement TEXT NOT NULL, fingerprint TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence_links(
 id TEXT PRIMARY KEY, claim_id TEXT NOT NULL REFERENCES claims(id),
 source_id TEXT NOT NULL REFERENCES sources(id), start_offset INTEGER NOT NULL,
 end_offset INTEGER NOT NULL, quote TEXT NOT NULL,
 stance TEXT NOT NULL CHECK(stance IN ('supports','contradicts','neutral')),
 fingerprint TEXT NOT NULL, rationale TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hypotheses(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 statement TEXT NOT NULL, mechanism TEXT NOT NULL, falsification TEXT NOT NULL,
 version INTEGER NOT NULL, predecessor TEXT REFERENCES hypotheses(id), actor TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS claims_no_update BEFORE UPDATE ON claims
 BEGIN SELECT RAISE(ABORT,'claims are immutable'); END;
CREATE TRIGGER IF NOT EXISTS claims_no_delete BEFORE DELETE ON claims
 BEGIN SELECT RAISE(ABORT,'claims are immutable'); END;
CREATE TRIGGER IF NOT EXISTS evidence_no_update BEFORE UPDATE ON evidence_links
 BEGIN SELECT RAISE(ABORT,'evidence links are immutable'); END;
CREATE TRIGGER IF NOT EXISTS evidence_no_delete BEFORE DELETE ON evidence_links
 BEGIN SELECT RAISE(ABORT,'evidence links are immutable'); END;
CREATE TRIGGER IF NOT EXISTS hypotheses_no_update BEFORE UPDATE ON hypotheses
 BEGIN SELECT RAISE(ABORT,'hypotheses are immutable'); END;
CREATE TRIGGER IF NOT EXISTS hypotheses_no_delete BEFORE DELETE ON hypotheses
 BEGIN SELECT RAISE(ABORT,'hypotheses are immutable'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
 BEGIN SELECT RAISE(ABORT,'audit records are immutable'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
 BEGIN SELECT RAISE(ABORT,'audit records are immutable'); END;
INSERT OR IGNORE INTO schema_versions VALUES(3);
