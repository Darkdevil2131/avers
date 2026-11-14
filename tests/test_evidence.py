from test_research import client, project, source
from ares.evidence import compare_context
CONTEXT = {
    "subject": "coating", "variable": "humidity", "units": "% RH",
    "population_or_material": "material A", "conditions": "25 C",
    "study_design": "bench experiment", "outcome": "retained strength",
    "measurement": "tensile test", "timeframe": "7 days",
}


def test_comparison_preserves_case_of_scientific_unit_symbols():
    assert compare_context({**CONTEXT, 'units': 'MPa'}, {**CONTEXT, 'units': 'mPa'}) == {
        'state': 'context-mismatched', 'fields': ['units'],
    }
def test_contextual_evidence_retraction_and_study_grouping(tmp_path):
    c = client(tmp_path)
    pid = project(c)
    s = source(c, pid)
    claim = c.post(f"/projects/{pid}/claims", json={
        "statement": "Humidity reduces the strength of coating A.", "fingerprint": CONTEXT
    }).json()["id"]
    base = {"source_id": s["id"], "start_offset": 0, "end_offset": 30,
            "stance": "supports", "fingerprint": CONTEXT, "rationale": "Synthetic reviewer assertion"}
    endpoint = f"/projects/{pid}/claims/{claim}/evidence"
    result = c.post(endpoint, json=base).json()
    assert result["assessment"] == "supported"
    assert result["basis"] == "reviewer-entered evidence relationships"
    assert result["confidence"] is None and result["independence_verified"] is False
    c.post(endpoint, json=base)
    assert c.get(f"/projects/{pid}/claims").json()[0]["study_groups"] == 1
    result = c.post(endpoint, json={**base, "stance": "contradicts"}).json()
    assert result["assessment"] == "mixed"
    c.post(f"/projects/{pid}/sources/{s['id']}/review", json={"status": "retracted", "reason": "Synthetic retraction"})
    assert c.get(f"/projects/{pid}/claims").json()[0]["assessment"] == "retracted-source"
def test_missing_and_mismatched_context_cannot_establish_support(tmp_path):
    c = client(tmp_path)
    pid = project(c)
    s = source(c, pid)
    claim = c.post(f"/projects/{pid}/claims", json={
        "statement": "Humidity reduces strength.", "fingerprint": CONTEXT
    }).json()["id"]
    endpoint = f"/projects/{pid}/claims/{claim}/evidence"
    body = {"source_id": s["id"], "start_offset": 0, "end_offset": 30,
            "stance": "supports", "fingerprint": {}, "rationale": "Synthetic reviewer assertion"}
    assert c.post(endpoint, json=body).json()["assessment"] == "unverified"
    body["fingerprint"] = {**CONTEXT, "conditions": "100 C"}
    assert c.post(endpoint, json=body).json()["assessment"] == "context-mismatched"
    body["end_offset"] = 1000000
    assert c.post(endpoint, json=body).status_code == 422
    foreign = project(c)
    body["end_offset"] = 30
    assert c.post(f"/projects/{foreign}/claims/{claim}/evidence", json=body).status_code == 404
def test_hypothesis_history_keeps_predecessor_and_requires_falsification(tmp_path):
    c = client(tmp_path)
    pid = project(c)
    proposal = {"statement": "A thicker coating may reduce humidity sensitivity.",
                "mechanism": "Proposed slower moisture transport.",
                "falsification": "Reject if thickness does not change measured transport under controlled conditions."}
    first = c.post(f"/projects/{pid}/hypotheses", json=proposal).json()
    second = c.post(f"/projects/{pid}/hypotheses", json={**proposal, "predecessor": first["id"]}).json()
    history = c.get(f"/projects/{pid}/hypotheses").json()
    assert len(history) == 2 and second["version"] == 2
    assert all(item["experiment_executed"] is False for item in history)
    assert c.post(f"/projects/{pid}/hypotheses", json={**proposal, "falsification": ""}).status_code == 422
