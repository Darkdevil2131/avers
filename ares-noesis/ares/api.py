"""Private, offline research intake. Every database operation has a project scope."""
import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class RunInput(BaseModel):
    question: str = Field(min_length=8, max_length=2000)


class SourceInput(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    text: str = Field(min_length=1, max_length=100000)
    license_status: str = Field(min_length=1, max_length=200)


SCHEMA = """
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
"""


def create_app(database: Path, credentials: dict[str, str]) -> FastAPI:
    if not credentials or len(set(credentials.values())) != len(credentials):
        raise ValueError("Configure distinct credentials for named users")
    if any(not user.strip() or len(token) < 32 for user, token in credentials.items()):
        raise ValueError("Credentials require a user name and at least 32 characters")
    digests = {
        user: hashlib.sha256(token.encode()).digest()
        for user, token in credentials.items()
    }
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)

    def connection():
        db = sqlite3.connect(database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    with closing(connection()) as db:
        db.executescript(SCHEMA)
        db.commit()

    app = FastAPI(title="ARES", version="0.1.0")

    def authenticate(authorization: str = Header(default="")):
        scheme, _, token = authorization.partition(" ")
        digest = hashlib.sha256(token.encode()).digest()
        if scheme.lower() == "bearer":
            for user, expected in digests.items():
                if secrets.compare_digest(digest, expected):
                    return user
        raise HTTPException(401, "Valid bearer credentials required")

    def authorize(db, project_id, user):
        project = db.execute(
            "SELECT id FROM projects WHERE id=? AND owner=?", (project_id, user)
        ).fetchone()
        if project is None:
            raise HTTPException(404, "Project not found")

    def timestamp():
        return datetime.now(timezone.utc).isoformat()

    @app.get("/health")
    def health():
        with closing(connection()) as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok", "mode": "offline-foundation"}

    @app.post("/projects", status_code=201)
    def create_project(body: ProjectInput, user=Depends(authenticate)):
        identifier = str(uuid4())
        with closing(connection()) as db, db:
            db.execute("INSERT INTO projects VALUES(?,?,?)", (identifier, user, body.name))
        return {"id": identifier, "name": body.name}

    @app.get("/projects")
    def projects(user=Depends(authenticate)):
        with closing(connection()) as db:
            return [dict(row) for row in db.execute(
                "SELECT id,name FROM projects WHERE owner=? ORDER BY id", (user,)
            )]

    @app.post("/projects/{project_id}/runs", status_code=201)
    def create_run(project_id: str, body: RunInput, user=Depends(authenticate)):
        identifier = str(uuid4())
        with closing(connection()) as db, db:
            authorize(db, project_id, user)
            db.execute("INSERT INTO runs VALUES(?,?,?,?)",
                       (identifier, project_id, body.question, timestamp()))
        return {"id": identifier, "status": "recorded", "assessment": "unverified"}

    @app.get("/projects/{project_id}/runs/{run_id}")
    def run(project_id: str, run_id: str, user=Depends(authenticate)):
        with closing(connection()) as db:
            authorize(db, project_id, user)
            row = db.execute(
                "SELECT * FROM runs WHERE id=? AND project_id=?", (run_id, project_id)
            ).fetchone()
            if row is None:
                raise HTTPException(404, "Run not found")
        return {**dict(row), "status": "recorded", "assessment": "unverified"}

    @app.post("/projects/{project_id}/sources", status_code=201)
    def source(project_id: str, body: SourceInput, user=Depends(authenticate)):
        digest = hashlib.sha256(body.text.encode()).hexdigest()
        with closing(connection()) as db, db:
            authorize(db, project_id, user)
            db.execute(
                "INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?,?,?)",
                (str(uuid4()), project_id, body.url, body.text, digest,
                 body.license_status, timestamp()),
            )
            row = db.execute(
                "SELECT id,digest,created_at FROM sources WHERE project_id=? "
                "AND url=? AND digest=? AND license_status=?",
                (project_id, body.url, digest, body.license_status),
            ).fetchone()
        return {**dict(row), "origin": "user_supplied", "verification": "unverified"}

    @app.get("/projects/{project_id}/sources")
    def sources(project_id: str, user=Depends(authenticate)):
        with closing(connection()) as db:
            authorize(db, project_id, user)
            return [dict(row) for row in db.execute(
                "SELECT * FROM sources WHERE project_id=? ORDER BY created_at,id", (project_id,)
            )]

    return app


def app_factory():
    credentials = json.loads(os.environ.get("ARES_CREDENTIALS", "{}"))
    return create_app(Path(os.environ.get("ARES_DATABASE", "state/ares.db")), credentials)
