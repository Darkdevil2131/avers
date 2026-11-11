import json
import re

import httpx

from noesis.api.main import create_app
from noesis.connectors.base import Paper
from noesis.corpus import store as corpus
from noesis.llm.client import LLMClient
from tests.conftest import authenticated_client, make_pdf
from tests.test_llm import reply

Q = "Does graphene coating increase battery lifespan?"


def paper(title, abstract, doi, author):
    return Paper(source="openalex", title=title, abstract=abstract, doi=doi, authors=[author], license="cc-by", year=2022)


SUPPORT_A = paper("Graphene coating extends battery lifespan", "We found that graphene coating increases battery lifespan in a randomized benchmark.", "10.1/a", "Ana Lopez")
SUPPORT_B = paper("Coated cells last longer", "We found that graphene coating increases battery lifespan across 40 coated cells.", "10.1/b", "Cy Dahl")
OPPOSE = paper("Graphene coating hurts lifespan", "We found that graphene coating decreases battery lifespan in small tests.", "10.1/c", "Bo Chen")


def app_with(env, papers, llm=None, offline=True):
    settings, sf, store = env
    settings.offline = offline
    s = sf()
    corpus.upsert(s, papers, "technology", "seed")
    s.commit()
    c = authenticated_client(create_app(settings, sf, store, connectors={}, llm_client=llm))
    pid = c.post("/api/v1/projects", json={"name": "q"}).json()["id"]
    return c, pid


def ask(c, pid, q=Q):
    r = c.post(f"/api/v1/projects/{pid}/query", json={"question": q})
    assert r.status_code == 202, r.text
    return c.get(f"/api/v1/jobs/{r.json()['job_id']}").json()


def test_query_with_independent_support_passes_gate_and_reports(env):
    c, pid = app_with(env, [SUPPORT_A, SUPPORT_B, OPPOSE])
    job = ask(c, pid)
    assert job["status"] == "completed", job
    u = job["result"]["understanding"]
    assert u["routing"]["domains"] == ["technology"] and u["question_type"] in ("causal", "factual")
    m = job["result"]["coverage"][0]
    assert m["hypothesis"] == "graphene coating increases battery lifespan" and m["origin"] == "rule"
    assert m["status"] in ("covered", "partial") and m["n_effective"] >= 2
    rep = c.get(f"/api/v1/projects/{pid}/report").json()["markdown"]
    assert "## 3. Coverage matrix" in rep and "Veracity Gate" in rep and "Graphene coating hurts lifespan" in rep   # opposing evidence is shown
    assert "[stance is unvalidated]" in rep and "NOT calibrated" in rep
    assert all("doi:" in line for line in rep.splitlines() if line.startswith("- **supports**"))


def test_veracity_gate_withholds_answer_when_evidence_is_thin(env):
    c, pid = app_with(env, [SUPPORT_A])
    job = ask(c, pid)
    cov = job["result"]["coverage"][0]
    assert cov["gate"]["passed"] is False and cov["n_effective"] == 1
    rep = c.get(f"/api/v1/projects/{pid}/report").json()["markdown"]
    assert "No answer is shown" in rep and "refuses to state a conclusion" in rep


def test_empty_corpus_degrades_honestly(env):
    c, pid = app_with(env, [])
    job = ask(c, pid)
    assert job["status"] == "completed"
    assert job["result"]["coverage"][0]["status"] == "no_evidence" and not job["result"]["coverage"][0]["gate"]["passed"]
    assert "No retrieved paper bore on this hypothesis" in c.get(f"/api/v1/projects/{pid}/report").json()["markdown"]


def test_query_with_llm_uses_grounded_stances(env):
    settings = env[0]
    settings.llm_api_key = "k"

    def anthropic(req):
        user = json.loads(req.content)["messages"][0]["content"]
        if "Parse the research question" in user:
            return reply({"question_type": "causal", "concepts": ["graphene coating", "battery lifespan"], "constraints": "", "time_range": ""})
        if "testable hypotheses" in user:
            return reply({"hypotheses": [{"subject": "Graphene coating", "relation": "increases", "object": "battery lifespan", "rationale": "barrier"}]})
        passage = re.search(r"<source>(.*)</source>", user, re.S).group(1)
        if "decreases battery lifespan" in passage:      # model invents a quote -> must be downgraded
            return reply({"stance": "contradicts", "evidence_quote": "this exact sentence is not in the abstract", "rationale": "x"})
        return reply({"stance": "supports", "evidence_quote": "graphene coating increases battery lifespan", "rationale": "same"})

    llm = LLMClient(settings, client=httpx.Client(transport=httpx.MockTransport(anthropic)), sleep=lambda s: None)
    c, pid = app_with(env, [SUPPORT_A, SUPPORT_B, OPPOSE], llm, offline=False)
    job = ask(c, pid)
    assert job["status"] == "completed", job
    assert job["result"]["understanding"]["method"] == "llm_v1" and job["result"]["coverage"][0]["origin"] == "llm_proposal"
    b = c.get(f"/api/v1/projects/{pid}/beliefs").json()[0]
    stances = sorted(e["stance"] for e in b["evidence"])
    assert stances == ["neutral", "supports", "supports"]               # the ungrounded "contradicts" did not count
    assert job["result"]["coverage"][0]["gate"]["passed"] is True


def test_human_feedback_is_audited_and_reversible(env):
    c, pid = app_with(env, [SUPPORT_A, SUPPORT_B])
    ask(c, pid)
    b = c.get(f"/api/v1/projects/{pid}/beliefs").json()[0]
    r = c.post(f"/api/v1/beliefs/{b['id']}/feedback", json={"action": "invalidate", "reason": "reviewer found the benchmark flawed"})
    assert r.json()["status"] == "invalidated"
    hist = c.get(f"/api/v1/beliefs/{b['id']}/history").json()
    assert "reviewer found the benchmark flawed" in hist[-1]["reason"]
    v = hist[-2]["version"]
    assert c.post(f"/api/v1/beliefs/{b['id']}/feedback", json={"action": "restore", "reason": "reviewer reversed", "version": v}).json()["status"] == "active"
    assert c.post(f"/api/v1/beliefs/{b['id']}/feedback", json={"action": "restore", "reason": "no version"}).status_code == 422
    assert c.post("/api/v1/beliefs/9999/feedback", json={"action": "dispute", "reason": "xxx"}).status_code == 404


def test_query_validation_and_project_scope(env):
    c, pid = app_with(env, [])
    assert c.post("/api/v1/projects/999/query", json={"question": Q}).status_code == 404
    assert c.post(f"/api/v1/projects/{pid}/query", json={"question": "short"}).status_code == 422
    assert c.post("/api/v1/engines/statistical_engine/run", json={"params": {"operation": "meta_analysis", "effects": [0.3, 0.5], "ses": [0.1, 0.1]}}).json()["k"] == 2


# ---- engine routing in query mode (gap found in the readiness audit: the query path never called an engine)
STAT_PAPER = paper("Humidity and perovskite degradation", "Humidity leads to perovskite degradation, t(28) = 2.10, p = .045 in 30 films.", "10.1/s", "Di Roy")


def test_query_routes_evidence_through_engines_and_never_stays_silent(env):
    c, pid = app_with(env, [STAT_PAPER, SUPPORT_A])
    job = ask(c, pid, "Does humidity cause perovskite degradation?")
    assert job["status"] == "completed", job
    runs = {r["engine"]: r for r in job["result"]["engine_runs"]}
    assert runs["statistical_engine"]["status"] == "ok" and runs["statistical_engine"]["n_inputs"] >= 1      # the p-value was recomputed by SciPy
    assert runs["statistical_engine"]["result"]["n_checked"] >= 1
    assert runs["causal_engine"]["status"] == "ok"                                                           # causal question -> causal audit ran
    assert runs["causal_engine"]["result"]["n_causal_claims"] >= 1
    assert "mathematical/simulation" in runs and runs["mathematical/simulation"]["status"] == "not_applicable"
    rep = c.get(f"/api/v1/projects/{pid}/report").json()["markdown"]
    assert "## Engine runs" in rep and "statistical_engine" in rep


def test_engine_with_no_input_reports_not_applicable_not_silence(env):
    c, pid = app_with(env, [SUPPORT_B])
    job = ask(c, pid)
    runs = {r["engine"]: r for r in job["result"]["engine_runs"]}
    assert runs["statistical_engine"]["status"] == "not_applicable" and "no extractable input" in runs["statistical_engine"]["reason"]


def test_belief_history_is_append_only_in_the_database(env):
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import DatabaseError
    c, pid = app_with(env, [SUPPORT_A, SUPPORT_B])
    ask(c, pid)
    sf = env[1]
    s = sf()
    assert s.execute(text("select count(*) from belief_events")).scalar() > 0
    with pytest.raises(DatabaseError, match="append-only"):
        s.execute(text("update belief_events set reason='tampered'"))
    s.rollback()
    with pytest.raises(DatabaseError, match="append-only"):
        s.execute(text("delete from belief_events"))
    s.rollback()
    s.close()
