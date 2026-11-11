"""Authenticated research API and browser workspace."""
import asyncio
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .database import AccessDenied, StorageBudget, Database, now
from .evidence import ClaimInput, EvidenceInput, HypothesisInput, assess
from .providers import EuropePMC
from .research import ResearchEngine
from .retrieval import hybrid_search
from .security import BodyLimit, RateLimit
from .tools import CAPABILITIES, execute


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class RunInput(BaseModel):
    question: str = Field(min_length=8, max_length=2000)
    external: bool = False


class SourceInput(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    text: str = Field(min_length=1, max_length=100000)
    license_status: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=500)
    study_id: str = Field(default="", max_length=500)


class ReviewInput(BaseModel):
    status: Literal["active", "retracted", "excluded"]
    reason: str = Field(min_length=8, max_length=2000)


class MemberInput(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    role: Literal["editor", "viewer"]


class FeedbackInput(BaseModel):
    source_id: str
    relevant: bool


class ToolInput(BaseModel):
    parameters: dict


def create_app(database: Path, credentials: dict[str, str], *, provider=None, auto_process=True) -> FastAPI:
    if not credentials or len(set(credentials.values())) != len(credentials):
        raise ValueError("Configure distinct credentials for named users")
    if any(not user.strip() or len(token) < 32 for user, token in credentials.items()):
        raise ValueError("Credentials require a user name and at least 32 characters")
    digests = {user: hashlib.sha256(token.encode()).digest() for user, token in credentials.items()}
    storage = Database(database)
    engine = ResearchEngine(storage, provider or EuropePMC())
    app = FastAPI(title="ARES", version="0.3.0")
    app.add_middleware(BodyLimit)
    app.state.storage, app.state.engine = storage, engine
    limiter = RateLimit()

    @app.exception_handler(StorageBudget)
    async def storage_error(request, exc):
        return JSONResponse({"detail":str(exc)},status_code=413)

    @app.exception_handler(AccessDenied)
    async def access_error(request, exc):
        return JSONResponse({"detail": "Project not found or action unavailable"}, status_code=404)

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
        )
        return response

    def authenticate(authorization: str = Header(default="")):
        scheme, _, token = authorization.partition(" ")
        digest = hashlib.sha256(token.encode()).digest()
        if scheme.lower() == "bearer":
            for user, expected in digests.items():
                if secrets.compare_digest(digest, expected):
                    return user
        raise HTTPException(401, "Valid bearer credentials required")

    def limited(user=Depends(authenticate)):
        if not limiter.allow(user):
            raise HTTPException(429, "Request budget reached; retry in one minute", headers={"Retry-After": "60"})
        return user

    def require_run(db, project_id, run_id):
        row = storage.run(db, project_id, run_id)
        if row is None:
            raise HTTPException(404, "Run not found")
        return row

    @app.get("/health")
    def health():
        with storage.connect() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok", "mode": "deterministic-research", "version": "0.3.0"}

    @app.get("/session")
    def session(user=Depends(authenticate)):
        return {"username": user, "mode": "local-model-assisted" if os.environ.get("ARES_REASONER_MODEL") else "extractive", "paid_services": False}

    @app.post("/projects", status_code=201)
    def create_project(body: ProjectInput, user=Depends(limited)):
        identifier = str(uuid4())
        with storage.connect() as db:
            db.execute("INSERT INTO projects VALUES(?,?,?)", (identifier, user, body.name))
            db.execute("INSERT INTO memberships VALUES(?,?,?)", (identifier, user, "owner"))
            storage.audit(db, identifier, user, "project_created", {})
        return {"id": identifier, "name": body.name, "role": "owner"}

    @app.get("/projects")
    def projects(user=Depends(authenticate)):
        with storage.connect() as db:
            return [dict(row) for row in db.execute("""
                SELECT p.id,p.name,m.role FROM projects p JOIN memberships m ON m.project_id=p.id
                WHERE m.username=? ORDER BY p.rowid DESC
            """, (user,))]

    @app.put("/projects/{project_id}/members")
    def membership(project_id: str, body: MemberInput, user=Depends(limited)):
        with storage.connect() as db:
            storage.authorize(db, project_id, user, owner=True)
            if body.username not in credentials:
                raise HTTPException(422, "User is not configured")
            if db.execute("SELECT 1 FROM memberships WHERE project_id=? AND username=? AND role='owner'",
                          (project_id, body.username)).fetchone():
                raise HTTPException(422, "Owner role cannot be changed here")
            db.execute("INSERT INTO memberships VALUES(?,?,?) ON CONFLICT(project_id,username) DO UPDATE SET role=excluded.role",
                       (project_id, body.username, body.role))
            storage.audit(db, project_id, user, "membership_changed", body.model_dump())
        return {"status": "saved"}

    @app.post("/projects/{project_id}/runs", status_code=201)
    def create_run(project_id: str, body: RunInput, tasks: BackgroundTasks,
                   user=Depends(limited), idempotency_key: str | None = Header(default=None, max_length=100)):
        identifier = str(uuid4())
        with storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            storage.authorize(db, project_id, user, write=True)
            existing = db.execute("SELECT run_id FROM run_state WHERE project_id=? AND request_key=?",
                                  (project_id, idempotency_key)).fetchone() if idempotency_key else None
            if existing:
                old = require_run(db, project_id, existing["run_id"])
                if old["question"] != body.question or bool(old["external"]) != body.external:
                    raise HTTPException(409, "Idempotency key belongs to another request")
                return old
            db.execute("INSERT INTO runs VALUES(?,?,?,?)", (identifier, project_id, body.question, now()))
            db.execute("INSERT INTO run_state(run_id,status,external,request_key,project_id) VALUES(?,?,?,?,?)",
                       (identifier, "queued", int(body.external), idempotency_key, project_id))
            storage.event(db, identifier, "queued", {"question": body.question})
            storage.audit(db, project_id, user, "run_queued", {"run_id": identifier})
        if auto_process:
            tasks.add_task(engine.execute, identifier)
        return {"id": identifier, "status": "queued", "assessment": "unverified"}

    @app.get("/projects/{project_id}/runs")
    def runs(project_id: str, user=Depends(authenticate)):
        with storage.connect() as db:
            storage.authorize(db, project_id, user)
            return [dict(row) for row in db.execute("""
                SELECT r.*,s.status,s.error FROM runs r JOIN run_state s ON s.run_id=r.id
                WHERE r.project_id=? ORDER BY r.created_at DESC LIMIT 100
            """, (project_id,))]

    @app.get("/projects/{project_id}/runs/{run_id}")
    def run(project_id: str, run_id: str, user=Depends(authenticate)):
        with storage.connect() as db:
            storage.authorize(db, project_id, user)
            return require_run(db, project_id, run_id)

    @app.post("/projects/{project_id}/runs/{run_id}/cancel")
    def cancel(project_id: str, run_id: str, user=Depends(limited)):
        with storage.connect() as db:
            storage.authorize(db, project_id, user, write=True)
            state = require_run(db, project_id, run_id)
            if state["status"] in {"queued", "running"}:
                db.execute("UPDATE run_state SET cancelled=1,status='cancelled' WHERE run_id=?", (run_id,))
                storage.event(db, run_id, "cancelled", {"actor": user})
        return {"status": "cancelled" if state["status"] in {"queued", "running"} else state["status"]}

    @app.get("/projects/{project_id}/runs/{run_id}/events")
    def events(project_id: str, run_id: str, after: int = Query(default=0, ge=0), user=Depends(authenticate)):
        with storage.connect() as db:
            storage.authorize(db, project_id, user)
            require_run(db, project_id, run_id)
            rows = db.execute("SELECT * FROM run_events WHERE run_id=? AND id>? ORDER BY id LIMIT 200",
                              (run_id, after)).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    @app.get("/projects/{project_id}/runs/{run_id}/stream")
    def stream(project_id: str, run_id: str, request: Request, after: int = Query(default=0, ge=0),
               user=Depends(authenticate)):
        with storage.connect() as db:
            storage.authorize(db, project_id, user)
            require_run(db, project_id, run_id)

        async def generate():
            cursor = after
            for _ in range(600):
                if await request.is_disconnected():
                    return
                batch = events(project_id, run_id, cursor, user)
                for event in batch:
                    cursor = event["id"]
                    yield f"id: {cursor}\ndata: {json.dumps(event)}\n\n"
                state = run(project_id, run_id, user)
                if state["status"] in {"completed", "failed", "cancelled"}:
                    yield f"event: done\ndata: {json.dumps({'status': state['status']})}\n\n"
                    return
                yield ": waiting\n\n"
                await asyncio.sleep(.5)
        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.get("/projects/{project_id}/runs/{run_id}/report")
    def report(project_id: str, run_id: str, user=Depends(authenticate)):
        with storage.connect() as db:
            storage.authorize(db, project_id, user)
            require_run(db, project_id, run_id)
            result = storage.report(db, project_id, run_id)
            if result is None:
                raise HTTPException(409, "Report is not ready")
            return result

    @app.get("/projects/{project_id}/runs/{run_id}/report.md")
    def download_report(project_id: str, run_id: str, user=Depends(authenticate)):
        result = report(project_id, run_id, user)
        return PlainTextResponse(result["markdown"], headers={"Content-Disposition": 'attachment; filename="ares-report.md"'})

    @app.post("/projects/{project_id}/sources", status_code=201)
    def source(project_id: str, body: SourceInput, user=Depends(limited)):
        with storage.connect() as db:
            storage.authorize(db, project_id, user, write=True)
            row = storage.add_source(db, project_id, body.model_dump(), user)
        return {**row, "origin": "user_supplied", "verification": "unverified"}

    @app.get("/projects/{project_id}/sources")
    def sources(project_id: str, user=Depends(authenticate)):
        with storage.connect() as db:
            storage.authorize(db, project_id, user)
            return [dict(row) for row in db.execute("""
                SELECT s.*,coalesce(d.title,s.url) AS title,coalesce(d.origin,'user_supplied') AS origin,
                coalesce((SELECT status FROM source_reviews WHERE source_id=s.id ORDER BY id DESC LIMIT 1),'active') AS status
                FROM sources s LEFT JOIN source_details d ON d.source_id=s.id
                WHERE s.project_id=? ORDER BY s.created_at DESC LIMIT 500
            """, (project_id,))]

    @app.post("/projects/{project_id}/sources/{source_id}/review")
    def review_source(project_id: str, source_id: str, body: ReviewInput, user=Depends(limited)):
        with storage.connect() as db:
            storage.authorize(db, project_id, user, write=True)
            if db.execute("SELECT 1 FROM sources WHERE id=? AND project_id=?", (source_id, project_id)).fetchone() is None:
                raise HTTPException(404, "Source not found")
            db.execute("INSERT INTO source_reviews(source_id,status,reason,actor,created_at) VALUES(?,?,?,?,?)",
                       (source_id, body.status, body.reason, user, now()))
            storage.audit(db, project_id, user, "source_reviewed", {"source_id": source_id, **body.model_dump()})
        return {"status": body.status}

    @app.get("/projects/{project_id}/search")
    def search(project_id: str, q: str = Query(min_length=1, max_length=2000), user=Depends(limited)):
        with storage.connect() as db:
            storage.authorize(db, project_id, user)
            return storage.search(db, project_id, q)

    @app.get("/capabilities")
    def capabilities(user=Depends(authenticate)):
        return CAPABILITIES

    @app.post("/projects/{project_id}/tools/{name}")
    def tool(project_id: str, name: str, body: ToolInput, user=Depends(limited)):
        with storage.connect() as db:
            storage.authorize(db, project_id, user, write=True)
            try:
                result = execute(name, body.parameters)
            except (ValueError, TypeError, OverflowError) as exc:
                raise HTTPException(422, str(exc)) from exc
            storage.audit(db, project_id, user, "tool_executed", {"name": name, "input": body.parameters, "output": result})
        return {"tool": name, "result": result, "version": CAPABILITIES[name]["version"]}

    @app.get("/projects/{project_id}/audit")
    def audit(project_id: str, user=Depends(authenticate)):
        with storage.connect() as db:
            storage.authorize(db, project_id, user, owner=True)
            return [dict(row) for row in db.execute(
                "SELECT * FROM audit_events WHERE project_id=? ORDER BY id DESC LIMIT 100", (project_id,)
            )]

    @app.post("/projects/{project_id}/claims", status_code=201)
    def claim(project_id: str, body: ClaimInput, user=Depends(limited)):
        identifier = str(uuid4())
        with storage.connect() as db:
            storage.authorize(db, project_id, user, write=True)
            db.execute("INSERT INTO claims VALUES(?,?,?,?,?,?)",
                       (identifier, project_id, body.statement, body.fingerprint.model_dump_json(), user, now()))
            storage.audit(db, project_id, user, "claim_recorded", {"claim_id": identifier})
        return {"id": identifier, "assessment": "unverified"}

    @app.get("/projects/{project_id}/claims")
    def claims(project_id: str, user=Depends(authenticate)):
        with storage.connect() as db:
            storage.authorize(db, project_id, user)
            return [assess(db, row) for row in db.execute(
                "SELECT * FROM claims WHERE project_id=? ORDER BY created_at DESC LIMIT 100", (project_id,)
            ).fetchall()]

    @app.post("/projects/{project_id}/claims/{claim_id}/evidence", status_code=201)
    def evidence(project_id: str, claim_id: str, body: EvidenceInput, user=Depends(limited)):
        identifier = str(uuid4())
        with storage.connect() as db:
            storage.authorize(db, project_id, user, write=True)
            claim = db.execute("SELECT * FROM claims WHERE id=? AND project_id=?", (claim_id, project_id)).fetchone()
            source = db.execute("SELECT * FROM sources WHERE id=? AND project_id=?", (body.source_id, project_id)).fetchone()
            if claim is None or source is None:
                raise HTTPException(404, "Claim or source not found")
            if body.end_offset <= body.start_offset or body.end_offset > len(source["text"]):
                raise HTTPException(422, "Offsets must identify an exact source span")
            quote = source["text"][body.start_offset:body.end_offset]
            db.execute("INSERT INTO evidence_links VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (identifier, claim_id, body.source_id, body.start_offset, body.end_offset, quote,
                        body.stance, body.fingerprint.model_dump_json(), body.rationale, user, now()))
            storage.audit(db, project_id, user, "evidence_linked", {"claim_id": claim_id, "evidence_id": identifier})
            return assess(db, claim)

    @app.post("/projects/{project_id}/hypotheses", status_code=201)
    def hypothesis(project_id: str, body: HypothesisInput, user=Depends(limited)):
        identifier, version = str(uuid4()), 1
        with storage.connect() as db:
            storage.authorize(db, project_id, user, write=True)
            if body.predecessor:
                previous = db.execute("SELECT version FROM hypotheses WHERE id=? AND project_id=?",
                                      (body.predecessor, project_id)).fetchone()
                if previous is None:
                    raise HTTPException(404, "Predecessor not found")
                version = previous["version"] + 1
            db.execute("INSERT INTO hypotheses VALUES(?,?,?,?,?,?,?,?,?)",
                       (identifier, project_id, body.statement, body.mechanism, body.falsification,
                        version, body.predecessor, user, now()))
            storage.audit(db, project_id, user, "hypothesis_proposed", {"id": identifier, "version": version})
        return {"id": identifier, "version": version, "status": "hypothesis", "experiment_executed": False}

    @app.get("/projects/{project_id}/hypotheses")
    def hypotheses(project_id: str, user=Depends(authenticate)):
        with storage.connect() as db:
            storage.authorize(db, project_id, user)
            return [{**dict(row), "status": "hypothesis", "experiment_executed": False} for row in db.execute(
                "SELECT * FROM hypotheses WHERE project_id=? ORDER BY created_at DESC LIMIT 100", (project_id,)
            )]

    @app.get("/projects/{project_id}/sources/{source_id}/document")
    def original_document(project_id: str, source_id: str, user=Depends(authenticate)):
        with storage.connect() as db:
            storage.authorize(db,project_id,user)
            row=db.execute("SELECT d.metadata FROM documents d JOIN sources s ON s.id=d.source_id WHERE s.project_id=? AND s.id=?",(project_id,source_id)).fetchone()
            if not row:raise HTTPException(404,"Original structured document not available")
            return json.loads(row['metadata'])

    @app.get("/projects/{project_id}/retrieve")
    def retrieve(project_id: str, q: str = Query(min_length=3,max_length=2000), user=Depends(limited)):
        with storage.connect() as db:
            storage.authorize(db,project_id,user)
            passages, details=hybrid_search(storage,db,project_id,q)
            return {"passages":passages,"retrieval":details}

    @app.post("/projects/{project_id}/runs/{run_id}/feedback")
    def feedback(project_id: str, run_id: str, body: FeedbackInput, user=Depends(limited)):
        with storage.connect() as db:
            storage.authorize(db,project_id,user,owner=True)
            require_run(db,project_id,run_id)
            report=storage.report(db,project_id,run_id)
            if not report or body.source_id not in {c['source_id'] for c in report['citations']}:
                raise HTTPException(422,"Feedback must refer to a source cited in this report")
            db.execute("INSERT INTO feedback(project_id,run_id,source_id,relevant,actor,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,run_id,source_id,actor) DO UPDATE SET relevant=excluded.relevant,created_at=excluded.created_at",(project_id,run_id,body.source_id,int(body.relevant),user,now()))
            storage.audit(db,project_id,user,"relevance_feedback",{"run_id":run_id,**body.model_dump()})
            return {"status":"saved","learning":"Future similar queries can use reviewed relevance feedback","truth_updated":False}

    @app.get("/projects/{project_id}/memory")
    def memory(project_id: str, user=Depends(authenticate)):
        with storage.connect() as db:
            storage.authorize(db,project_id,user)
            result=[]
            for row in db.execute("SELECT * FROM research_memory WHERE project_id=? ORDER BY created_at DESC LIMIT 100",(project_id,)):
                item=dict(row);item["content"]=json.loads(item["content"])
                report=storage.report(db,project_id,item["run_id"])
                item["stale"]=bool(report and report["outdated_sources"])
                result.append(item)
            return result

    @app.post("/projects/{project_id}/memory/{memory_id}/review")
    def memory_review(project_id: str, memory_id: str, body: ReviewInput, user=Depends(limited)):
        with storage.connect() as db:
            storage.authorize(db,project_id,user,owner=True)
            row=db.execute("SELECT * FROM research_memory WHERE id=? AND project_id=?",(memory_id,project_id)).fetchone()
            if row is None:raise HTTPException(404,"Memory not found")
            report=storage.report(db,project_id,row["run_id"])
            if body.status=='active' and report["outdated_sources"]:
                raise HTTPException(409,"Source reviews changed; run research again before approving memory")
            status='approved' if body.status=='active' else 'rejected'
            db.execute("UPDATE research_memory SET status=?,actor=? WHERE id=?",(status,user,memory_id))
            storage.audit(db,project_id,user,"memory_reviewed",{"memory_id":memory_id,"status":status,"reason":body.reason})
            return {"status":status,"model_weights_updated":False}

    static = Path(__file__).parent / "static"
    if static.exists():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def workspace():
            return FileResponse(static / "index.html")
    return app


def app_factory():
    credentials = json.loads(os.environ.get("ARES_CREDENTIALS", "{}"))
    return create_app(Path(os.environ.get("ARES_DATABASE", "state/ares.db")), credentials,
                      auto_process=os.environ.get("ARES_QUEUE_MODE", "inline") == "inline")
