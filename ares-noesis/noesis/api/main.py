"""REST API (v1). Long jobs run in the background; clients poll /jobs/{id}."""
import secrets
from datetime import datetime, timezone

from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import pipeline
from ..belief.engine import BeliefEngine
from ..config import get_settings
from ..connectors.sources import default_connectors
from ..db import make_engine, make_session_factory
from ..engines import registry
from ..graph import evidence_graph as eg
from ..corpus import store as corpus_store
from ..corpus.index import CorpusIndex
from ..ingestion.parse import InvalidDocument, parse_document, sha256_hex, validate_upload
from ..query.pipeline import run_query_job
from .. import auth as authlib, worker
from ..models import User
from ..models import AuditLog, Belief, Claim, Document, ExternalPaper, Hypothesis, Job, Project, Report
from ..storage import get_store


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class SyncIn(BaseModel):
    topics: list[str] = Field(min_length=1, max_length=10)
    domain: str = Field(pattern="^(medicine|technology|space)$")
    sources: list[str] = Field(default_factory=lambda: ["openalex", "arxiv", "crossref", "europepmc"])
    limit: int = Field(default=100, ge=1, le=1000)


class QueryIn(BaseModel):
    question: str = Field(min_length=8, max_length=1000)


class FeedbackIn(BaseModel):
    action: str = Field(pattern="^(dispute|invalidate|restore)$")
    reason: str = Field(min_length=3, max_length=500)
    version: int | None = None


class RateLimiter:
    """Sliding-window limiter, in-process (per API replica). Behind several replicas use a shared store (Redis) or a gateway."""

    def __init__(self, limit: int, window: float = 60.0):
        import collections
        import threading
        self.limit, self.window, self.hits, self.lock = limit, window, collections.defaultdict(collections.deque), threading.Lock()

    def check(self, key: str):
        import time
        if self.limit <= 0:
            return
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                raise HTTPException(429, "rate limit exceeded; slow down", headers={"Retry-After": str(int(self.window - (now - q[0])) + 1)})
            q.append(now)


_DUMMY_HASH = authlib.hash_password("not-a-real-password")


class Creds(BaseModel):
    email: str = Field(min_length=5, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=10, max_length=200)


class EngineRun(BaseModel):
    params: dict = Field(default_factory=dict)


def create_app(settings=None, session_factory=None, store=None, connectors=None, llm_client=None) -> FastAPI:
    settings = settings or get_settings()
    if settings.auth_mode not in {"api_key", "none", "users"}:
        raise RuntimeError("NOESIS_AUTH_MODE must be api_key or users")

    def valid_secret(value):
        return len(value.strip()) >= 32 and value.isascii()

    if settings.auth_mode == "users":
        if not valid_secret(settings.secret_key):
            raise RuntimeError("NOESIS_SECRET_KEY must be at least 32 ASCII characters")
        if settings.api_key and not valid_secret(settings.api_key):
            raise RuntimeError("NOESIS_API_KEY must be at least 32 ASCII characters")
    elif not valid_secret(settings.api_key):
        raise RuntimeError("NOESIS_API_KEY must be at least 32 ASCII characters")

    def matches_key(value):
        return bool(settings.api_key) and secrets.compare_digest(value.encode(), settings.api_key.encode())

    sf = session_factory or make_session_factory(make_engine(settings.database_url))
    store = store or get_store(settings)
    app = FastAPI(title="Noesis", version="0.1.0")
    import threading
    import time as _time
    counters: dict = {}
    lock = threading.Lock()

    @app.middleware("http")
    async def count_requests(request, call_next):
        t0 = _time.perf_counter()
        resp = await call_next(request)
        route = request.scope.get("route")
        key = (request.method, getattr(route, "path", "unmatched"), resp.status_code)
        with lock:
            c = counters.setdefault(key, [0, 0.0])
            c[0] += 1
            c[1] += _time.perf_counter() - t0
        return resp

    app.state.connectors = connectors
    app.state.llm_client = llm_client

    def auth(x_api_key: str = Header(default=""), authorization: str = Header(default="")):
        """Returns {'id','role'} in users mode, else None. Raises 401 when credentials are missing/invalid."""
        if settings.auth_mode == "users":
            tok = authorization[7:] if authorization.lower().startswith("bearer ") else ""
            u = authlib.parse_token(tok, settings.secret_key) if tok else None
            if not u:
                raise HTTPException(401, "login required (Authorization: Bearer <token>)")
            return u
        if not matches_key(x_api_key):
            raise HTTPException(401, "invalid or missing X-API-Key")
        return None

    def access(s, pid, user):
        p = s.get(Project, pid)
        if not p or (user and user["role"] != "admin" and p.owner_id != user["id"]):
            raise HTTPException(404, "project not found")   # 404 (not 403) so other users' project ids are not revealed
        return p

    limiter, login_limiter = RateLimiter(settings.rate_limit_per_min), RateLimiter(settings.login_rate_limit_per_min)

    def throttle(request: Request, user=Depends(auth)):
        limiter.check(f"{(user or {}).get('id', '')}|{request.client.host if request.client else '?'}")

    def dispatch(bg, job, fn, *args):
        """inline: run as a background task. db: leave the queued row for `noesis worker`."""
        if settings.queue_mode != "db":
            bg.add_task(fn, *args)

    def db():
        s = sf()
        try:
            yield s
        finally:
            s.close()


    @app.post("/api/v1/auth/register", status_code=201)
    def register(body: Creds, request: Request, x_api_key: str = Header(default=""), s=Depends(db)):
        if settings.auth_mode != "users":
            raise HTTPException(404, "accounts are disabled (NOESIS_AUTH_MODE != users)")
        login_limiter.check(request.client.host if request.client else "?")
        first = s.scalar(select(User.id).limit(1)) is None
        if first and not matches_key(x_api_key):
            raise HTTPException(403, "administrator setup requires X-API-Key")
        if not first and not settings.allow_registration:
            raise HTTPException(403, "registration is closed")
        if s.scalars(select(User).where(User.email == body.email.lower())).first():
            raise HTTPException(409, "email already registered")
        u = User(email=body.email.lower(), password_hash=authlib.hash_password(body.password), role="admin" if first else "researcher")
        s.add(u)
        s.commit()
        return {"id": u.id, "email": u.email, "role": u.role}

    @app.post("/api/v1/auth/login")
    def login(body: Creds, request: Request, s=Depends(db)):
        login_limiter.check(request.client.host if request.client else "?")
        u = s.scalars(select(User).where(User.email == body.email.lower())).first() if settings.auth_mode == "users" else None
        ok = authlib.verify_password(body.password, u.password_hash if u else _DUMMY_HASH)   # same work whether or not the account exists
        if not u or not ok:
            raise HTTPException(401, "invalid email or password")
        return {"token": authlib.make_token(u.id, u.role, settings.secret_key, settings.token_ttl_hours * 3600), "role": u.role}

    @app.get("/", include_in_schema=False)
    def ui():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    api = "/api/v1"

    @app.post(f"{api}/projects", dependencies=[Depends(auth)], status_code=201)
    def create_project(body: ProjectIn, s=Depends(db), user=Depends(auth)):
        p = Project(name=body.name, owner_id=(user or {}).get("id"))
        s.add(p)
        s.commit()
        return {"id": p.id, "name": p.name}

    @app.get(f"{api}/projects", dependencies=[Depends(auth)])
    def list_projects(s=Depends(db), user=Depends(auth)):
        q = select(Project)
        if user and user["role"] != "admin":
            q = q.where(Project.owner_id == user["id"])
        return [{"id": p.id, "name": p.name} for p in s.scalars(q)]

    @app.post(f"{api}/projects/{{pid}}/documents", dependencies=[Depends(auth)], status_code=201)
    async def upload(pid: int, file: UploadFile = File(...), s=Depends(db), user=Depends(auth), _t=Depends(throttle)):
        access(s, pid, user)
        limit, buf = settings.max_upload_mb * 1024 * 1024, bytearray()
        while chunk := await file.read(1024 * 1024):      # never buffer more than limit+1 chunk
            buf += chunk
            if len(buf) > limit:
                raise HTTPException(413, f"file exceeds the {settings.max_upload_mb} MB limit")
        data = bytes(buf)
        try:
            validate_upload(file.filename or "", data, settings.max_upload_mb * 1024 * 1024)
            parse_document(file.filename, data, settings.max_upload_mb * 1024 * 1024, settings.max_pages)  # reject unreadable docs up-front
        except InvalidDocument as e:
            raise HTTPException(422, str(e))
        sha = sha256_hex(data)
        dup = s.scalars(select(Document).where(Document.project_id == pid, Document.sha256 == sha)).first()
        if dup:
            return {"id": dup.id, "duplicate": True, "sha256": sha}
        key = f"projects/{pid}/originals/{sha}"
        store.put(key, data)
        d = Document(project_id=pid, filename=file.filename, sha256=sha, blob_key=key)
        s.add(d)
        s.add(AuditLog(project_id=pid, actor="api", action="upload", detail={"sha256": sha, "filename": file.filename}))
        s.commit()
        return {"id": d.id, "duplicate": False, "sha256": sha}

    @app.post(f"{api}/projects/{{pid}}/documents/{{did}}/analyze", dependencies=[Depends(auth)], status_code=202)
    def analyze(pid: int, did: int, bg: BackgroundTasks, s=Depends(db), user=Depends(auth), _t=Depends(throttle)):
        access(s, pid, user)
        d = s.get(Document, did)
        if not d or d.project_id != pid:
            raise HTTPException(404, "document not found")
        from datetime import datetime, timedelta, timezone
        horizon = datetime.now(timezone.utc) - timedelta(seconds=settings.lease_seconds)
        for other in s.scalars(select(Job).where(Job.document_id == did, Job.status.in_(["queued", "running"]))):
            created = other.created_at if other.created_at.tzinfo else other.created_at.replace(tzinfo=timezone.utc)
            if other.status == "queued" or created > horizon:       # an old 'running' row with a dead worker is not blocking
                raise HTTPException(409, {"message": "this document is already being analysed", "job_id": other.id})
        j = Job(project_id=pid, document_id=did, kind="analyze_document", payload={}, attempts=0)
        s.add(j)
        s.commit()
        dispatch(bg, j, pipeline.analyze_document, sf, store, settings, j.id,
                 app.state.connectors if app.state.connectors is not None else default_connectors(settings), app.state.llm_client)
        return {"job_id": j.id, "status": "queued"}

    @app.post(f"{api}/projects/{{pid}}/query", dependencies=[Depends(auth)], status_code=202)
    def query(pid: int, body: QueryIn, bg: BackgroundTasks, s=Depends(db), user=Depends(auth), _t=Depends(throttle)):
        access(s, pid, user)
        j = Job(project_id=pid, kind="query", payload={"question": body.question}, attempts=0)
        s.add(j)
        s.add(AuditLog(project_id=pid, actor="api", action="query", detail={"question": body.question[:200]}))
        s.commit()
        dispatch(bg, j, run_query_job, sf, settings, j.id, body.question,
                 app.state.connectors if app.state.connectors is not None else default_connectors(settings), app.state.llm_client)
        return {"job_id": j.id, "status": "queued"}

    @app.post(f"{api}/beliefs/{{bid}}/feedback", dependencies=[Depends(auth)])
    def belief_feedback(bid: int, body: FeedbackIn, s=Depends(db), user=Depends(auth)):
        """Human-in-the-loop: a researcher disputes/invalidates a belief or restores an earlier version. Fully audited."""
        b = s.get(Belief, bid)
        if not b:
            raise HTTPException(404, "belief not found")
        access(s, b.project_id, user)
        be = BeliefEngine(s)
        try:
            if body.action == "dispute":
                be.mark_disputed(bid, f"researcher feedback: {body.reason}")
            elif body.action == "invalidate":
                be.invalidate(bid, f"researcher feedback: {body.reason}")
            else:
                if body.version is None:
                    raise HTTPException(422, "restore needs a version")
                be.restore(bid, body.version, f"researcher feedback: {body.reason}")
        except ValueError as e:
            raise HTTPException(404, str(e))
        s.add(AuditLog(project_id=b.project_id, actor="api", action=f"belief_{body.action}", detail={"belief": bid, "reason": body.reason}))
        s.commit()
        return {"id": bid, "status": b.status, "assessment": b.assessment, "version": b.version}

    @app.get(f"{api}/jobs/{{jid}}", dependencies=[Depends(auth)])
    def job(jid: int, s=Depends(db), user=Depends(auth)):
        j = s.get(Job, jid)
        if not j:
            raise HTTPException(404, "job not found")
        access(s, j.project_id, user)
        return {"id": j.id, "status": j.status, "error": j.error, "result": j.result}

    @app.get(f"{api}/projects/{{pid}}/claims", dependencies=[Depends(auth)])
    def claims(pid: int, s=Depends(db), user=Depends(auth)):
        access(s, pid, user)
        q = select(Claim).join(Document, Claim.document_id == Document.id).where(Document.project_id == pid)
        return [{"id": c.id, "document_id": c.document_id, "text": c.text, "page": c.page, "section": c.section, "kind": c.kind, "meta": c.meta} for c in s.scalars(q)]

    @app.get(f"{api}/projects/{{pid}}/beliefs", dependencies=[Depends(auth)])
    def beliefs(pid: int, s=Depends(db), user=Depends(auth)):
        access(s, pid, user)
        return pipeline._belief_dicts(s, pid)

    @app.get(f"{api}/beliefs/{{bid}}/history", dependencies=[Depends(auth)])
    def belief_history(bid: int, s=Depends(db), user=Depends(auth)):
        b = s.get(Belief, bid)
        if not b:
            raise HTTPException(404, "belief not found")
        access(s, b.project_id, user)
        return BeliefEngine(s).history(bid)

    @app.post(f"{api}/beliefs/{{bid}}/restore/{{version}}", dependencies=[Depends(auth)])
    def belief_restore(bid: int, version: int, s=Depends(db), user=Depends(auth)):
        b0 = s.get(Belief, bid)
        if not b0:
            raise HTTPException(404, "belief not found")
        access(s, b0.project_id, user)
        try:
            b = BeliefEngine(s).restore(bid, version, "via API")
        except ValueError as e:
            raise HTTPException(404, str(e))
        s.commit()
        return {"id": b.id, "version": b.version, "assessment": b.assessment}

    @app.get(f"{api}/projects/{{pid}}/hypotheses", dependencies=[Depends(auth)])
    def hypotheses(pid: int, s=Depends(db), user=Depends(auth)):
        access(s, pid, user)
        return [h.payload for h in s.scalars(select(Hypothesis).where(Hypothesis.project_id == pid))]

    @app.get(f"{api}/projects/{{pid}}/graph", dependencies=[Depends(auth)])
    def graph(pid: int, s=Depends(db), user=Depends(auth)):
        access(s, pid, user)
        return eg.to_json(eg.build_graph(s, pid))

    @app.get(f"{api}/projects/{{pid}}/report", dependencies=[Depends(auth)])
    def report(pid: int, s=Depends(db), user=Depends(auth)):
        access(s, pid, user)
        r = s.scalars(select(Report).where(Report.project_id == pid).order_by(Report.id.desc())).first()
        if not r:
            raise HTTPException(404, "no report yet - run /analyze first")
        return {"id": r.id, "markdown": r.markdown}

    @app.get(f"{api}/projects/{{pid}}/papers", dependencies=[Depends(auth)])
    def papers(pid: int, s=Depends(db), user=Depends(auth)):
        access(s, pid, user)
        return [{"id": p.id, "source": p.source, "title": p.title, "doi": p.doi, "license": p.license, "retracted": p.retracted}
                for p in s.scalars(select(ExternalPaper).where(ExternalPaper.project_id == pid))]

    @app.get(f"{api}/corpus/stats", dependencies=[Depends(auth)])
    def corpus_stats(s=Depends(db), user=Depends(auth)):
        return corpus_store.stats(s)

    @app.get(f"{api}/corpus/search", dependencies=[Depends(auth)])
    def corpus_search(q: str = Query(min_length=1, max_length=500), k: int = Query(10, ge=1, le=50), s=Depends(db), user=Depends(auth)):
        return [{"score": round(sc, 3), "id": p.id, "title": p.title, "source": p.source, "doi": p.doi, "year": p.year,
                 "design": p.design, "domain": p.domain, "license": p.license, "retracted": p.retracted}
                for p, sc in CorpusIndex(s).search(q, k)]

    @app.post(f"{api}/corpus/sync", dependencies=[Depends(auth)], status_code=202)
    def corpus_sync(body: SyncIn, bg: BackgroundTasks, user=Depends(auth), _t=Depends(throttle)):
        if user and user["role"] != "admin":
            raise HTTPException(403, "only admins can harvest into the shared corpus")
        conns = app.state.connectors if app.state.connectors is not None else default_connectors(settings)
        def run():
            for t in body.topics:
                corpus_store.sync_topic(sf, conns, t, body.domain, body.sources, body.limit)
        bg.add_task(run)
        return {"status": "started", "topics": body.topics}

    @app.get(f"{api}/corpus/runs", dependencies=[Depends(auth)])
    def corpus_runs(s=Depends(db), user=Depends(auth)):
        if user and user["role"] != "admin":
            raise HTTPException(403, "admin only")
        from ..models import SyncRun
        return [{"id": r.id, "source": r.source, "query": r.query, "status": r.status, "fetched": r.n_fetched, "new": r.n_new, "error": r.error}
                for r in s.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(50))]

    @app.get("/metrics", include_in_schema=False)
    def metrics(s=Depends(db), user=Depends(auth)):
        """Prometheus text exposition: request counts/latency by route, jobs by status, corpus and belief sizes."""
        from fastapi.responses import PlainTextResponse
        from sqlalchemy import func
        from ..models import CorpusPaper
        if user and user["role"] != "admin":
            raise HTTPException(403, "admin only")
        L = ["# TYPE noesis_http_requests_total counter", "# TYPE noesis_http_request_seconds_sum counter"]
        with lock:
            for (m, path, code), (n, sec) in sorted(counters.items()):
                lab = f'method="{m}",route="{path}",status="{code}"'
                L += [f"noesis_http_requests_total{{{lab}}} {n}", f"noesis_http_request_seconds_sum{{{lab}}} {sec:.6f}"]
        L.append("# TYPE noesis_jobs gauge")
        for st_, n in s.execute(select(Job.status, func.count(Job.id)).group_by(Job.status)):
            L.append(f'noesis_jobs{{status="{st_}"}} {n}')
        L += ["# TYPE noesis_corpus_papers gauge", f"noesis_corpus_papers {s.scalar(select(func.count(CorpusPaper.id)))}",
              "# TYPE noesis_beliefs gauge", f"noesis_beliefs {s.scalar(select(func.count(Belief.id)))}"]
        return PlainTextResponse("\n".join(L) + "\n")

    @app.get(f"{api}/engines", dependencies=[Depends(auth)])
    def engines():
        return registry.profiles()

    @app.post(f"{api}/engines/{{name}}/run", dependencies=[Depends(auth)])
    def run_engine(name: str, body: EngineRun, user=Depends(auth), _t=Depends(throttle)):
        if user and user["role"] != "admin":
            raise HTTPException(403, "admin only")
        eng = registry.ENGINES.get(name)
        if not eng:
            raise HTTPException(404, "unknown engine")
        try:
            import json as _json
            res = eng["run"](body.params)
            # engines may leak numpy/SymPy scalars; normalise to plain JSON so serialisation can never 500
            return _json.loads(_json.dumps(res, default=lambda o: float(o) if hasattr(o, "__float__") else str(o)))
        except (ValueError, KeyError) as e:
            raise HTTPException(422, f"invalid engine input: {e}")

    @app.get(f"{api}/connectors", dependencies=[Depends(auth)])
    def connectors_status():
        return [c.describe() for c in default_connectors(settings).values()]

    return app


def app_factory():
    return create_app()
