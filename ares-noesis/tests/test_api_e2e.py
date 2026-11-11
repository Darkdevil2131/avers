from fastapi.testclient import TestClient

from noesis.api.main import create_app
from noesis.config import Settings
from tests.conftest import authenticated_client, make_pdf, mock_connectors


def _run(client, pdf=None, name="paper.pdf"):
    pid = client.post("/api/v1/projects", json={"name": "t"}).json()["id"]
    up = client.post(f"/api/v1/projects/{pid}/documents", files={"file": (name, pdf or make_pdf(), "application/pdf")})
    assert up.status_code == 201, up.text
    r = client.post(f"/api/v1/projects/{pid}/documents/{up.json()['id']}/analyze")
    assert r.status_code == 202
    job = client.get(f"/api/v1/jobs/{r.json()['job_id']}").json()
    return pid, up.json(), job


def test_full_workflow_with_external_evidence(client):
    pid, up, job = _run(client)
    assert job["status"] == "completed", job
    tasks = job["result"]["tasks"]
    assert tasks["stat_check"]["output"]["n_problems"] == 1          # t(28)=1.20, p=.03 is a decision error
    assert tasks["math_check"]["output"]["results"][0]["verdict"] == "identity"
    assert tasks["acquire_technology"]["status"] in ("completed", "partial")
    assert all(t["status"] in ("completed", "partial") for t in tasks.values()), tasks

    claims = client.get(f"/api/v1/projects/{pid}/claims").json()
    assert any(c["kind"] == "finding" and c["page"] == 1 for c in claims)

    beliefs = client.get(f"/api/v1/projects/{pid}/beliefs").json()
    b = next(b for b in beliefs if "graphene coating increases" in b["claim_text"])
    assert b["support_class"] == "partially_supported" or b["support_class"] == "directly_supported"
    ext = [e for e in b["evidence"] if e["group"] != "source_document"]
    assert {"supports", "contradicts"} <= {e["stance"] for e in ext}
    assert all(e["criteria"] for e in ext)                              # every grade shows its criteria
    sup = next(e for e in ext if e["stance"] == "supports")
    assert sup["design"] == "benchmark" and sup["grade"] == 3   # "randomized benchmark" is not an RCT
    flagged = next(b for b in beliefs if "humidity" in b["claim_text"].lower())
    assert any("inconsistent" in f for f in flagged["flags"])
    hist = client.get(f"/api/v1/beliefs/{b['id']}/history").json()
    assert hist[0]["action"] == "create" and all(h["reason"] for h in hist)

    hyps = client.get(f"/api/v1/projects/{pid}/hypotheses").json()
    assert hyps and all(h["confidence"] is None and h["status"] != "established" for h in hyps)
    assert any("energy retention" in h["statement"] for h in hyps)
    planned = [h for h in hyps if h["proposed_experiment"]]
    assert planned and all(h["proposed_experiment"]["executed"] is False for h in planned)

    g = client.get(f"/api/v1/projects/{pid}/graph").json()
    kinds = {n["type"] for n in g["nodes"]}
    assert {"document", "claim", "paper", "belief", "evidence", "entity"} <= kinds

    rep = client.get(f"/api/v1/projects/{pid}/report").json()["markdown"]
    for n in range(1, 26):
        assert f"## {n}. " in rep
    assert "decision_error" in rep and "proposal only" in rep and "calibrated: false" in rep
    assert "10.1000/xyz123" in rep and "[HYPOTHESIS" in rep
    papers = client.get(f"/api/v1/projects/{pid}/papers").json()
    assert len(papers) == 3 and all(p["license"] for p in papers)


def test_graceful_degradation_when_apis_down(env):
    settings, sf, store = env
    app = create_app(settings, sf, store, connectors=mock_connectors(status=503))
    c = authenticated_client(app)
    pid, _, job = _run(c)
    assert job["status"] == "completed"
    acq = job["result"]["tasks"]["acquire_technology"]
    assert acq["status"] == "partial" or acq["status"] == "completed"
    assert acq["output"]["n_papers"] == 0 and acq["output"]["errors"]
    beliefs = c.get(f"/api/v1/projects/{pid}/beliefs").json()
    assert all(b["support_class"] == "not_independently_verifiable" for b in beliefs)   # honest: no fake evidence
    rep = c.get(f"/api/v1/projects/{pid}/report").json()["markdown"]
    assert "No external literature was retrieved" in rep


def test_offline_mode_runs_without_acquisition(env):
    settings, sf, store = env
    settings.offline = True
    c = authenticated_client(create_app(settings, sf, store, connectors=mock_connectors()))
    _, _, job = _run(c)
    assert job["status"] == "completed" and not any(k.startswith("acquire") for k in job["result"]["tasks"])


def test_duplicate_upload_and_reanalysis_idempotent(client):
    pdf = make_pdf()
    pid, up, job = _run(client, pdf)
    again = client.post(f"/api/v1/projects/{pid}/documents", files={"file": ("paper.pdf", pdf, "application/pdf")}).json()
    assert again["duplicate"] is True and again["id"] == up["id"]
    n1 = len(client.get(f"/api/v1/projects/{pid}/claims").json())
    client.post(f"/api/v1/projects/{pid}/documents/{up['id']}/analyze")
    assert len(client.get(f"/api/v1/projects/{pid}/claims").json()) == n1
    active = [b for b in client.get(f"/api/v1/projects/{pid}/beliefs").json()]
    assert len({b["claim_text"] for b in active}) == len(active)


def test_invalid_uploads_rejected(client):
    pid = client.post("/api/v1/projects", json={"name": "t"}).json()["id"]
    for name, data in [("x.exe", b"MZ"), ("x.pdf", b"nope"), ("x.pdf", b"%PDF-1.4 broken"), ("x.txt", b"")]:
        r = client.post(f"/api/v1/projects/{pid}/documents", files={"file": (name, data)})
        assert r.status_code == 422, (name, r.text)
    assert client.post("/api/v1/projects/999/documents", files={"file": ("a.txt", b"hello world " * 20)}).status_code == 404


def test_engine_endpoint_and_input_validation(client):
    r = client.post("/api/v1/engines/stats_engine/run", json={"params": {}})
    assert r.status_code == 404
    ok = client.post("/api/v1/engines/statistical_engine/run", json={"params": {"operation": "sample_size", "d": 0.5}})
    assert ok.json()["n_per_group"] == 64
    assert client.post("/api/v1/engines/statistical_engine/run", json={"params": {"operation": "nope"}}).status_code == 422
    inj = client.post("/api/v1/engines/math_engine/run", json={"params": {"operation": "check_equations", "equations": ["__import__('os').system('id') = 1"]}})
    assert inj.status_code == 200 and inj.json()["results"][0]["verdict"] in ("rejected_unsafe_input", "unparseable")


def test_api_key_enforced(env):
    settings, sf, store = env
    settings.api_key = "privatekey" * 4
    c = TestClient(create_app(settings, sf, store, connectors={}))
    assert c.post("/api/v1/projects", json={"name": "x"}).status_code == 401
    assert c.post("/api/v1/projects", json={"name": "x"}, headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.post("/api/v1/projects", json={"name": "x"}, headers={"X-API-Key": settings.api_key}).status_code == 201
    assert c.get("/health").status_code == 200


def test_project_isolation(client):
    p1, _, _ = _run(client)
    p2 = client.post("/api/v1/projects", json={"name": "other"}).json()["id"]
    assert client.get(f"/api/v1/projects/{p2}/claims").json() == []
    assert client.get(f"/api/v1/projects/{p2}/hypotheses").json() == []
    assert client.get(f"/api/v1/projects/{p2}/report").status_code == 404
    d = client.post(f"/api/v1/projects/{p1}/documents", files={"file": ("n.txt", b"Results\nDose increases yield. " * 5)}).json()["id"]
    assert client.post(f"/api/v1/projects/{p2}/documents/{d}/analyze").status_code == 404


def test_blob_store_blocks_path_traversal(env):
    import pytest
    _, _, store = env
    with pytest.raises(ValueError):
        store.put("../../etc/evil", b"x")


def test_ui_served_and_uses_only_existing_endpoints(client):
    import re
    from pathlib import Path
    r = client.get("/")
    assert r.status_code == 200 and "<title>Noesis</title>" in r.text
    html = Path("noesis/api/static/index.html").read_text()
    assert "innerHTML" not in html          # untrusted paper text must never be injected as markup
    routes = {x.path for x in client.app.routes}
    for ep in ["/projects", "/engines", "/connectors", "/jobs/{jid}", "/projects/{pid}/graph", "/projects/{pid}/report",
               "/projects/{pid}/beliefs", "/projects/{pid}/hypotheses", "/projects/{pid}/claims", "/beliefs/{bid}/history"]:
        assert "/api/v1" + ep in routes
    used = set(re.findall(r"api\(`?'?(/[a-z]+)", html))
    assert used <= {"/projects", "/engines", "/connectors", "/jobs", "/beliefs", "/corpus"}
