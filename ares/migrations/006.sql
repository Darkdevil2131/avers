CREATE UNIQUE INDEX IF NOT EXISTS runs_id_project_idx ON runs(id, project_id);
CREATE UNIQUE INDEX IF NOT EXISTS claims_id_project_idx ON claims(id, project_id);
CREATE TABLE IF NOT EXISTS run_claims(
 run_id TEXT PRIMARY KEY,
 project_id TEXT NOT NULL,
 claim_id TEXT NOT NULL,
 FOREIGN KEY (run_id, project_id) REFERENCES runs(id, project_id),
 FOREIGN KEY (claim_id, project_id) REFERENCES claims(id, project_id));
CREATE TRIGGER IF NOT EXISTS run_claims_no_update BEFORE UPDATE ON run_claims
 BEGIN SELECT RAISE(ABORT,'run claim selection is immutable'); END;
CREATE TRIGGER IF NOT EXISTS run_claims_no_delete BEFORE DELETE ON run_claims
 BEGIN SELECT RAISE(ABORT,'run claim selection is immutable'); END;
CREATE INDEX IF NOT EXISTS evidence_links_claim_idx ON evidence_links(claim_id, created_at, id);
INSERT OR IGNORE INTO schema_versions VALUES(6);
