from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from noesis import auth, worker
from noesis.api.main import create_app
from noesis.config import Settings
from noesis.db import Base, make_engine
from noesis.migrate import ensure_schema
from noesis.models import Job
from tests.conftest import authenticated_client, make_pdf, mock_connectors
from tests.test_query import SUPPORT_A, SUPPORT_B

SECRET = "x" * 32
PW = "correct-horse-battery"


def users_app(env, **kw):
    settings, sf, store = env
    settings.auth_mode, settings.secret_key, settings.allow_registration = "users", SECRET, True
    for k, v in kw.items():
        setattr(settings, k, v)
    return authenticated_client(create_app(settings, sf, store, connectors=mock_connectors())), settings


def login(c, email, register=True):
    if register:
        assert c.post("/api/v1/auth/register", json={"email": email, "password": PW}).status_code == 201
    t = c.post("/api/v1/auth/login", json={"email": email, "password": PW}).json()["token"]
    return {"Authorization": f"Bearer {t}"}


def test_password_hashing_and_tokens():
    h1, h2 = auth.hash_password(PW), auth.hash_password(PW)
    assert h1 != h2 and auth.verify_password(PW, h1) and not auth.verify_password("wrong-password!", h1) and not auth.verify_password(PW, "garbage")
    tok = auth.make_token(7, "researcher", SECRET, 60, now=1000)
    assert auth.parse_token(tok, SECRET, now=1030) == {"id": 7, "role": "researcher"}
    assert auth.parse_token(tok, SECRET, now=2000) is None                      # expired
    assert auth.parse_token(tok, "other-secret-other-secret", now=1030) is None   # wrong key
    body, sig = tok.split(".")
    assert auth.parse_token(body + "x." + sig, SECRET, now=1030) is None          # tampered


def test_users_are_isolated_from_each_other(env):
    c, _ = users_app(env)
    a = login(c, "admin@lab.edu")
    b = login(c, "bob@lab.edu")
    assert c.post("/api/v1/projects", json={"name": "x"}).status_code == 401
    pa = c.post("/api/v1/projects", json={"name": "bob's"}, headers=b).json()["id"]
    c.post("/api/v1/projects", json={"name": "other"}, headers=a)
    c2 = login(c, "eve@lab.edu")
    assert c.get(f"/api/v1/projects/{pa}/claims", headers=c2).status_code == 404          # eve cannot see bob's project
    assert c.get(f"/api/v1/projects/{pa}/claims", headers=b).status_code == 200
    assert c.get(f"/api/v1/projects/{pa}/claims", headers=a).status_code == 200            # admin can
    assert [p["name"] for p in c.get("/api/v1/projects", headers=c2).json()] == []
    up = c.post(f"/api/v1/projects/{pa}/documents", files={"file": ("p.pdf", make_pdf())}, headers=b).json()["id"]
    jid = c.post(f"/api/v1/projects/{pa}/documents/{up}/analyze", headers=b).json()["job_id"]
    assert c.get(f"/api/v1/jobs/{jid}", headers=b).status_code == 200
    assert c.get(f"/api/v1/jobs/{jid}", headers=c2).status_code == 404                      # job ids do not leak across users
    bid = c.get(f"/api/v1/projects/{pa}/beliefs", headers=b).json()[0]["id"]
    assert c.get(f"/api/v1/beliefs/{bid}/history", headers=c2).status_code == 404
    assert c.post(f"/api/v1/beliefs/{bid}/feedback", json={"action": "dispute", "reason": "mine"}, headers=c2).status_code == 404


def test_account_rules(env):
    c, s = users_app(env)
    assert c.post("/api/v1/auth/register", json={"email": "a@b.co", "password": "short"}).status_code == 422
    assert c.post("/api/v1/auth/register", json={"email": "not-an-email", "password": PW}).status_code == 422
    assert TestClient(c.app).post("/api/v1/auth/register", json={"email": "a@b.co", "password": PW}).status_code == 403
    first = c.post("/api/v1/auth/register", json={"email": "a@b.co", "password": PW}).json()
    assert first["role"] == "admin" and c.post("/api/v1/auth/register", json={"email": "A@B.co", "password": PW}).status_code == 409
    assert c.post("/api/v1/auth/login", json={"email": "a@b.co", "password": "wrong-password-1"}).status_code == 401
    s.allow_registration = False
    assert c.post("/api/v1/auth/register", json={"email": "c@d.co", "password": PW}).status_code == 403
    assert c.get("/api/v1/projects", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_only_admin_can_write_shared_corpus(env):
    c, s = users_app(env)
    adm = login(c, "admin@lab.edu"); usr = login(c, "u@lab.edu")
    body = {"topics": ["graphene"], "domain": "technology"}
    assert c.post("/api/v1/corpus/sync", json=body, headers=usr).status_code == 403
    assert c.post("/api/v1/corpus/sync", json=body, headers=adm).status_code == 202


def test_accounts_disabled_by_default_and_secret_required(env):
    settings, sf, store = env
    assert authenticated_client(create_app(settings, sf, store, connectors={})).post("/api/v1/auth/register", json={"email": "a@b.co", "password": PW}).status_code == 404
    settings.auth_mode = "users"
    import pytest
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(settings, sf, store, connectors={})


def test_db_queue_survives_api_restart_and_worker_completes_job(env):
    settings, sf, store = env
    settings.queue_mode, settings.offline = "db", True
    c = authenticated_client(create_app(settings, sf, store, connectors={}))
    pid = c.post("/api/v1/projects", json={"name": "q"}).json()["id"]
    did = c.post(f"/api/v1/projects/{pid}/documents", files={"file": ("p.pdf", make_pdf())}).json()["id"]
    jid = c.post(f"/api/v1/projects/{pid}/documents/{did}/analyze").json()["job_id"]
    assert c.get(f"/api/v1/jobs/{jid}").json()["status"] == "queued"                 # nothing ran in the API process
    assert worker.run_once(sf, store, settings, "w1", connectors={}) is True         # a separate worker picks it up
    j = c.get(f"/api/v1/jobs/{jid}").json()
    assert j["status"] == "completed" and j["result"]["tasks"]["report"]["status"] == "completed"
    assert worker.run_once(sf, store, settings, "w1", connectors={}) is False        # queue drained
    qj = c.post(f"/api/v1/projects/{pid}/query", json={"question": "Does graphene coating increase battery lifespan?"}).json()["job_id"]
    assert c.get(f"/api/v1/jobs/{qj}").json()["status"] == "queued"
    assert worker.run_once(sf, store, settings, "w2", connectors={}) and c.get(f"/api/v1/jobs/{qj}").json()["status"] == "completed"


def test_crashed_worker_job_is_reclaimed_then_given_up(env):
    settings, sf, store = env
    settings.queue_mode, settings.offline = "db", True
    c = authenticated_client(create_app(settings, sf, store, connectors={}))
    pid = c.post("/api/v1/projects", json={"name": "q"}).json()["id"]
    did = c.post(f"/api/v1/projects/{pid}/documents", files={"file": ("p.pdf", make_pdf())}).json()["id"]
    jid = c.post(f"/api/v1/projects/{pid}/documents/{did}/analyze").json()["job_id"]
    s = sf()
    j = s.get(Job, jid)
    j.status, j.worker_id, j.attempts = "running", "dead-worker", 1                   # a worker took it and died
    j.lease_until = datetime.now(timezone.utc) + timedelta(minutes=5)
    s.commit()
    assert worker.claim(sf, settings, "w2") is None                                   # lease still valid: not stolen
    j.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    s.commit()
    assert worker.run_once(sf, store, settings, "w2", connectors={})                  # lease expired: re-claimed and finished
    s.expire_all()
    assert s.get(Job, jid).status == "completed" and s.get(Job, jid).attempts == 2
    j2 = Job(project_id=pid, document_id=did, kind="analyze_document", status="running", attempts=settings.max_attempts, payload={},
             lease_until=datetime.now(timezone.utc) - timedelta(seconds=1))
    s.add(j2); s.commit()
    assert worker.run_once(sf, store, settings, "w3", connectors={}) is False
    s.expire_all()
    assert s.get(Job, j2.id).status == "failed" and "gave up" in s.get(Job, j2.id).error


def test_schema_sync_adds_missing_columns_to_an_old_database():
    eng = make_engine("sqlite://")
    with eng.begin() as cx:
        cx.execute(text("CREATE TABLE projects (id INTEGER PRIMARY KEY, name VARCHAR(200), created_at DATETIME)"))
        cx.execute(text("INSERT INTO projects (name) VALUES ('legacy')"))
    from noesis import models  # noqa: F401
    ensure_schema(eng, Base)
    assert "owner_id" in {c["name"] for c in inspect(eng).get_columns("projects")} and "lease_until" in {c["name"] for c in inspect(eng).get_columns("jobs")}
    with eng.begin() as cx:
        assert cx.execute(text("SELECT name FROM projects")).scalar() == "legacy"     # existing data preserved
