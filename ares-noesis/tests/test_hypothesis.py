import networkx as nx

from noesis.graph import evidence_graph as eg
from noesis.hypothesis import engine as hyp
from noesis.hypothesis.experiment import plan


def E_chain():
    E = nx.DiGraph()
    for n, d in (("a", ["technology"]), ("b", ["technology"]), ("c", ["medicine"])):
        E.add_node(f"entity:{n}", type="entity", label=n, domains=d)
    E.add_edge("entity:a", "entity:b", sources=["claim:1"], signs=[1])
    E.add_edge("entity:b", "entity:c", sources=["paper:2"], signs=[-1])
    return E


def test_gap_from_open_chain_with_sign_composition_and_cross_domain():
    gaps = eg.find_gaps(E_chain())
    assert len(gaps) == 1 and gaps[0]["sign"] == -1 and gaps[0]["mediators"] == ["entity:b"]
    hs = hyp.generate(E_chain(), [], ["unrelated text"], "2026-11-04")
    h = hs[0]
    assert h["generation_method"] == "cross_domain_link" and "decrease" in h["statement"] and h["confidence"] is None
    assert h["status"] == "candidate" and h["novelty_assessment"]["search_date"] == "2026-11-04"
    assert set(h["supporting_claims"]) == {"claim:1", "paper:2"}
    assert "unvalidated" in h["limitations"][0]


def test_novelty_flags_existing_cooccurrence_and_verification_status():
    hs = hyp.generate(E_chain(), [], ["we show a drives c in detail"], "2026-11-04")
    assert hs[0]["novelty_assessment"]["verdict"] == "possibly_already_described"
    v = hyp.verify(hs[0], E_chain(), [])
    assert v["status"] == "likely_already_described" and v["not_checked"]


def test_contradiction_driven_hypothesis():
    E = nx.DiGraph()
    E.add_edge("entity:x", "entity:y", sources=["paper:1", "paper:2"], signs=[1, -1])
    for n in ("x", "y"):
        E.nodes[f"entity:{n}"].update(type="entity", label=n, domains=["technology"])
    hs = hyp.generate(E, [], [], "2026-11-04")
    assert hs[0]["generation_method"] == "contradiction" and hs[0]["contradicting_claims"] == ["paper:2"]


def test_experiment_plan_is_proposal_with_real_power_calc():
    h = hyp.generate(E_chain(), [], [], "2026-11-04")[0]
    h["domain"] = ["medicine"]
    p = plan(h)
    assert p["executed"] is False and p["sample_size"]["n_per_group"] == 64
    assert "ASSUMPTION" in p["sample_size"]["caveat"] and p["failure_criteria"] and any("IRB" in e for e in p["ethical_requirements"])
