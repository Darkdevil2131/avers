import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
STOPWORDS = set("a an the is are does do of for and or to in on with how what which can this that by from".split())
def now():
    return datetime.now(timezone.utc).isoformat()
class StorageBudget(Exception):
    pass
class AccessDenied(Exception):
    pass
class Database:
    def __new__(cls,path):
        if cls is Database and str(path).startswith(('postgresql://','postgres://')):
            from .postgres import PostgresDatabase
            return object.__new__(PostgresDatabase)
        return object.__new__(cls)
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            for migration in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
                db.executescript(migration.read_text())
            for row in db.execute("SELECT * FROM sources WHERE id NOT IN (SELECT source_id FROM passages)").fetchall():
                self.index_source(db, dict(row))
    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()
    def authorize(self, db, project_id, user, write=False, owner=False):
        row = db.execute(
            "SELECT role FROM memberships WHERE project_id=? AND username=?", (project_id, user)
        ).fetchone()
        if row is None or (write and row["role"] == "viewer") or (owner and row["role"] != "owner"):
            raise AccessDenied()
        return row["role"]
    def audit(self, db, project_id, actor, action, detail):
        db.execute("INSERT INTO audit_events(project_id,actor,action,detail,created_at) VALUES(?,?,?,?,?)",
                   (project_id, actor, action, json.dumps(detail), now()))
    def event(self, db, run_id, stage, payload):
        db.execute("INSERT INTO run_events(run_id,stage,payload,created_at) VALUES(?,?,?,?)",
                   (run_id, stage, json.dumps(payload), now()))
    def index_source(self, db, source):
        text = source["text"]
        for start in range(0, len(text), 900):
            end = min(start + 1000, len(text))
            passage_id = f"{source['id']}:{start}"
            db.execute("INSERT OR IGNORE INTO passages VALUES(?,?,?,?,?,?)",
                       (passage_id, source["id"], source["project_id"], start, end, text[start:end]))
            if not db.execute("SELECT 1 FROM passage_search WHERE passage_id=?", (passage_id,)).fetchone():
                db.execute("INSERT INTO passage_search VALUES(?,?,?)",
                           (passage_id, source["project_id"], text[start:end]))
    def add_source(self, db, project_id, data, actor):
        digest = hashlib.sha256(data["text"].encode()).hexdigest()
        existing=db.execute("SELECT id FROM sources WHERE project_id=? AND url=? AND digest=? AND license_status=?",(project_id,data['url'],digest,data['license_status'])).fetchone()
        count,size=db.execute("SELECT count(*),coalesce(sum(length(text)),0) FROM sources WHERE project_id=?",(project_id,)).fetchone()
        if not existing and (count>=1000 or size+len(data['text'])>20_000_000):
            raise StorageBudget('Project source storage budget reached')
        db.execute("INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?,?,?)",
                   (str(uuid4()), project_id, data["url"], data["text"], digest, data["license_status"], now()))
        source = dict(db.execute(
            "SELECT * FROM sources WHERE project_id=? AND url=? AND digest=? AND license_status=?",
            (project_id, data["url"], digest, data["license_status"]),
        ).fetchone())
        db.execute("INSERT OR IGNORE INTO source_details VALUES(?,?,?,?)",
                   (source["id"], data.get("title") or data["url"],
                    data.get("study_id") or data["url"], data.get("origin", "user_supplied")))
        if data.get("document"):
            document_size=db.execute("SELECT coalesce(sum(length(d.metadata)),0) FROM documents d JOIN sources s ON s.id=d.source_id WHERE s.project_id=?",(project_id,)).fetchone()[0]
            if document_size+len(json.dumps(data['document']))>70_000_000:
                raise StorageBudget('Project original-document storage budget reached')
            db.execute("INSERT OR IGNORE INTO documents VALUES(?,?)", (source["id"], json.dumps(data["document"])))
        self.index_source(db, source)
        self.audit(db, project_id, actor, "source_ingested", {"source_id": source["id"], "digest": digest})
        return source
    def search(self, db, project_id, question, limit=8):
        terms = list(dict.fromkeys(
            t.lower() for t in re.findall(r"\w+", question, flags=re.UNICODE)
            if len(t) > 2 and t.lower() not in STOPWORDS
        ))[:30]
        if not terms:
            return []
        query = " OR ".join(f'"{term}"' for term in terms)
        rows = db.execute("""
            SELECT p.*, s.url, s.digest, s.license_status, s.created_at AS retrieved_at,
                   coalesce(d.title,s.url) AS title, coalesce(d.study_id,s.url) AS study_id,
                   coalesce(d.origin,'user_supplied') AS origin,
                   coalesce((SELECT max(id) FROM source_reviews WHERE source_id=s.id),0) AS review_version,
                   bm25(passage_search) AS rank
            FROM passage_search
            JOIN passages p ON p.id=passage_search.passage_id
            JOIN sources s ON s.id=p.source_id
            LEFT JOIN source_details d ON d.source_id=s.id
            WHERE passage_search MATCH ? AND p.project_id=?
              AND coalesce((SELECT status FROM source_reviews WHERE source_id=s.id ORDER BY id DESC LIMIT 1),'active')='active'
            ORDER BY rank,p.id LIMIT ?
        """, (query, project_id, limit)).fetchall()
        return [dict(row) for row in rows]
    def run(self, db, project_id, run_id):
        row = db.execute("""
            SELECT r.*,s.status,s.attempts,s.error,s.cancelled,s.external
            FROM runs r JOIN run_state s ON s.run_id=r.id WHERE r.id=? AND r.project_id=?
        """, (run_id, project_id)).fetchone()
        return dict(row) if row else None
    def report(self, db, project_id, run_id):
        row = db.execute("""
            SELECT reports.* FROM reports JOIN runs ON runs.id=reports.run_id
            WHERE reports.run_id=? AND runs.project_id=?
        """, (run_id, project_id)).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload"])
        changed = []
        for citation in payload["citations"]:
            version = db.execute("SELECT coalesce(max(id),0) FROM source_reviews WHERE source_id=?",
                                 (citation["source_id"],)).fetchone()[0]
            if version != citation["review_version"]:
                changed.append(citation["source_id"])
        return {**payload, "markdown": row["markdown"], "outdated_sources": sorted(set(changed))}
