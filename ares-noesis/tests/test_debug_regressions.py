"""Regression tests written BEFORE the fixes (reproduce -> isolate -> diagnose -> fix). Each docstring names the failure mode."""
import pymupdf
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from noesis import auth
from noesis.api.main import create_app
from noesis.belief.engine import BeliefEngine
from noesis.config import Settings
from noesis.connectors.base import Paper
from noesis.corpus import store
from noesis.corpus.index import CorpusIndex
from noesis.ingestion.parse import InvalidDocument, parse_document
from noesis.models import CorpusPaper, Document, Project
from noesis.planning import planner
from noesis.verification.evidence import EvidenceInput
from tests.conftest import authenticated_client, make_pdf, mock_connectors
from tests.test_corpus import P


def test_retraction_after_indexing_removes_paper_from_search(env):
    """BUG H1: index cache keyed on (count, max id) so flipping `retracted` did not invalidate it -> retracted papers kept being cited."""
    _, sf, _ = env
    s = sf()
    store.upsert(s, [P("Perovskite humidity degradation", "Moisture degrades perovskite solar cells.", "10.1/r")], "technology", "t")
    s.commit()
    assert CorpusIndex(s).search("perovskite humidity")
    row = s.scalars(select(CorpusPaper)).one()
    row.retracted = True
    s.commit()
    assert CorpusIndex(s).search("perovskite humidity") == []


def test_failed_task_does_not_poison_later_tasks_or_lose_earlier_work(env):
    """BUG H2: a DB error inside one task left the shared session in a failed state, so every later task died with PendingRollbackError
    (and a naive rollback would have discarded earlier tasks' uncommitted work)."""
    _, sf, _ = env
    s = sf()
    p = Project(name="x"); s.add(p); s.flush()
    s.add(Document(project_id=p.id, filename="a", sha256="dup", blob_key="k")); s.flush()

    class Ctx:
        pass
    ctx = Ctx(); ctx.s = s

    def good_first(c, t):
        c.s.add(Project(name="written-by-earlier-task")); c.s.flush(); return {}

    def db_error(c, t):
        c.s.add(Document(project_id=p.id, filename="b", sha256="dup", blob_key="k2")); c.s.flush(); return {}   # unique violation

    def good_later(c, t):
        return {"n": len(list(c.s.scalars(select(Project))))}

    plan = [planner.Task("a", "first"), planner.Task("b", "err", optional_deps=["a"]), planner.Task("c", "later", optional_deps=["b"])]
    res = planner.execute(plan, {"first": good_first, "err": db_error, "later": good_later}, ctx)
    assert res["b"]["status"] == "failed" and "IntegrityError" in res["b"]["error"]
    assert res["c"]["status"] == "completed" and res["c"]["output"]["n"] == 2          # session usable, earlier task's row still there


def test_oversize_upload_rejected_without_reading_whole_body(env):
    """BUG H3: whole upload was read into memory before the size check (memory DoS)."""
    settings, sf, store_ = env
    settings.max_upload_mb = 1
    c = authenticated_client(create_app(settings, sf, store_, connectors={}))
    pid = c.post("/api/v1/projects", json={"name": "x"}).json()["id"]
    r = c.post(f"/api/v1/projects/{pid}/documents", files={"file": ("big.txt", b"a" * (3 * 1024 * 1024))})
    assert r.status_code == 413 and "limit" in r.json()["detail"]


def test_rate_limit_protects_expensive_and_login_endpoints(env):
    """BUG H4/H16: no throttling: unlimited LLM-cost queries and unlimited password guesses."""
    settings, sf, store_ = env
    settings.rate_limit_per_min = 5
    settings.login_rate_limit_per_min = 3
    c = authenticated_client(create_app(settings, sf, store_, connectors={}))
    pid = c.post("/api/v1/projects", json={"name": "x"}).json()["id"]
    codes = [c.post(f"/api/v1/projects/{pid}/query", json={"question": "Does graphene coating increase battery lifespan?"}).status_code for _ in range(7)]
    assert codes[:5] == [202] * 5 and codes[5:] == [429, 429]
    r = c.post(f"/api/v1/projects/{pid}/query", json={"question": "Does graphene coating increase battery lifespan?"})
    assert r.status_code == 429 and "Retry-After" in r.headers
    settings.auth_mode, settings.secret_key = "users", "k" * 32
    c2 = authenticated_client(create_app(settings, sf, store_, connectors={}))
    bad = [c2.post("/api/v1/auth/login", json={"email": "a@b.co", "password": "wrong-password-1"}).status_code for _ in range(5)]
    assert bad == [401, 401, 401, 429, 429]


def test_double_analyze_returns_existing_job_instead_of_racing(env):
    """BUG H7: two concurrent analyses of one document both delete/recreate claims and corrupt each other."""
    settings, sf, store_ = env
    settings.queue_mode = "db"
    c = authenticated_client(create_app(settings, sf, store_, connectors={}))
    pid = c.post("/api/v1/projects", json={"name": "x"}).json()["id"]
    did = c.post(f"/api/v1/projects/{pid}/documents", files={"file": ("p.pdf", make_pdf())}).json()["id"]
    j1 = c.post(f"/api/v1/projects/{pid}/documents/{did}/analyze")
    j2 = c.post(f"/api/v1/projects/{pid}/documents/{did}/analyze")
    assert j1.status_code == 202 and j2.status_code == 409 and j2.json()["detail"]["job_id"] == j1.json()["job_id"]


def test_restore_refuses_when_evidence_was_moved_out_by_split(env):
    """BUG H8: restoring a version silently ignored evidence that a later split had moved to another belief -> a 'restored' belief that was not the old one."""
    _, sf, _ = env
    s = sf()
    p = Project(name="x"); s.add(p); s.flush()
    be = BeliefEngine(s)
    b = be.create(p.id, "A improves B")
    e1 = be.add_evidence(b.id, EvidenceInput(title="p1", design="rct", stance="supports", independence_group="g1"), "p1")
    be.add_evidence(b.id, EvidenceInput(title="p2", design="rct", stance="supports", independence_group="g2"), "p2")
    v_before = b.version
    be.split(b.id, [e1.id], "A improves B in study 1", "scope")
    with pytest.raises(ValueError, match="moved"):
        be.restore(b.id, v_before, "undo")


def test_pdf_page_bomb_is_rejected():
    """BUG H13: no page-count cap; a 10k-page PDF would be fully extracted."""
    doc = pymupdf.open()
    for i in range(6):
        doc.new_page().insert_text((72, 72), f"Results page {i}. " * 10)
    with pytest.raises(InvalidDocument, match="pages"):
        parse_document("b.pdf", doc.tobytes(), max_pages=5)
    assert parse_document("b.pdf", doc.tobytes(), max_pages=6).n_pages == 6


def test_login_does_not_leak_account_existence_by_timing(env, monkeypatch):
    """BUG H15: unknown email skipped password hashing -> measurable timing difference reveals which emails are registered."""
    settings, sf, store_ = env
    settings.auth_mode, settings.secret_key = "users", "k" * 32
    c = authenticated_client(create_app(settings, sf, store_, connectors={}))
    calls = []
    real = auth.verify_password
    monkeypatch.setattr(auth, "verify_password", lambda pw, h: (calls.append(1), real(pw, h))[1])
    assert c.post("/api/v1/auth/login", json={"email": "nobody@x.co", "password": "whatever-password"}).status_code == 401
    assert calls, "a hash verification must run even when the account does not exist"


def test_corpus_search_input_bounds(client):
    """BUG H11: negative k / giant q were passed straight to the index."""
    assert client.get("/api/v1/corpus/search", params={"q": "x" * 600}).status_code == 422
    assert client.get("/api/v1/corpus/search", params={"q": "ok", "k": 0}).status_code == 422
    assert client.get("/api/v1/corpus/search", params={"q": "ok", "k": -3}).status_code == 422


def test_engine_results_are_always_json_serialisable_through_the_api(client):
    """BUG H19: dimensionally-consistent results carried SymPy numbers (e.g. `One`) -> HTTP 500 / tool error, invisible to direct-call unit tests."""
    u = {"F": "N", "m": "kg", "a": "m/s**2", "E": "J", "v": "m/s"}
    r = client.post("/api/v1/engines/math_engine/run", json={"params": {"operation": "check_dimensions", "lhs": "F", "rhs": "m*a", "units": u}})
    assert r.status_code == 200 and r.json()["verdict"] == "dimensionally_consistent"
    assert r.json()["dimensions"] == {"length": 1, "mass": 1, "time": -2}
    r = client.post("/api/v1/engines/simulation_engine/run", json={"params": {"operation": "two_body", "r0": [7e6, 0, 0], "v0": [0, 7546, 0], "t_end": 600}})
    assert r.status_code == 200 and r.json()["conserved"] is True
    r = client.post("/api/v1/engines/statistical_engine/run", json={"params": {"operation": "meta_analysis", "effects": [0.1, 0.9, 0.5], "ses": [0.1, 0.1, 0.1]}})
    assert r.status_code == 200 and isinstance(r.json()["pooled"], float)
