CREATE TABLE IF NOT EXISTS documents(source_id TEXT PRIMARY KEY REFERENCES sources(id), metadata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS embeddings(passage_id TEXT NOT NULL REFERENCES passages(id),project_id TEXT NOT NULL REFERENCES projects(id),model TEXT NOT NULL,vector BLOB NOT NULL,text_hash TEXT NOT NULL,PRIMARY KEY(passage_id,model));
CREATE TABLE IF NOT EXISTS research_memory(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),run_id TEXT NOT NULL REFERENCES runs(id),content TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',actor TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY AUTOINCREMENT,project_id TEXT NOT NULL REFERENCES projects(id),run_id TEXT NOT NULL REFERENCES runs(id),source_id TEXT NOT NULL REFERENCES sources(id),relevant INTEGER NOT NULL CHECK(relevant IN (0,1)),actor TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(project_id,run_id,source_id,actor));
INSERT OR IGNORE INTO schema_versions VALUES(4);
CREATE TRIGGER IF NOT EXISTS documents_no_update BEFORE UPDATE ON documents
 BEGIN SELECT RAISE(ABORT,'original documents are immutable'); END;
CREATE TRIGGER IF NOT EXISTS documents_no_delete BEFORE DELETE ON documents
 BEGIN SELECT RAISE(ABORT,'original documents are immutable'); END;
