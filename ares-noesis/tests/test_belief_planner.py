from noesis.belief.engine import BeliefEngine, pool
from noesis.models import Project
from noesis.planning import planner
from noesis.planning.router import route
from noesis.verification.evidence import EvidenceInput, assess, classify_support


def ev(group, stance="supports", design="rct", **kw):
    return EvidenceInput(title=group, design=design, stance=stance, independence_group=group, **kw)


def test_grade_criteria_are_explicit():
    a = assess(EvidenceInput(design="rct", sample_size=12, peer_reviewed=False))
    assert a["grade"] == 2 and {c["criterion"] for c in a["criteria"]} >= {"study_design", "publication_status", "sample_size"}
    assert assess(EvidenceInput(design="rct", retracted=True))["grade"] == 0
    assert assess(EvidenceInput(design="cohort", independent_replication=True))["grade"] == 3


def test_dependent_evidence_not_double_counted():
    items = [{"stance": "supports", "grade": 3, "group": "author:lopez"}, {"stance": "supports", "grade": 3, "group": "author:lopez"},
             {"stance": "supports", "grade": 3, "group": "author:chen"}]
    assert pool(items)["n_effective"] == 2
    one = pool(items[:1])["posterior"]
    assert pool(items)["posterior"] > one and pool(items[:2])["posterior"] == one


def test_self_reported_carries_no_weight():
    p = pool([{"stance": "supports", "grade": 4, "group": "source_document"}])
    assert p["n_effective"] == 0 and p["assessment"] == "insufficient_evidence" and p["calibrated"] is False
    assert classify_support([{"stance": "supports", "grade": 4, "group": "source_document"}]) == "not_independently_verifiable"
    assert classify_support([]) == "unsupported"


def test_support_categories():
    s = lambda st, g, grp: {"stance": st, "grade": g, "group": grp}
    assert classify_support([s("supports", 4, "a")]) == "directly_supported"
    assert classify_support([s("supports", 2, "a")]) == "partially_supported"
    assert classify_support([s("contradicts", 3, "a")]) == "contradicted"
    assert classify_support([s("supports", 3, "a"), s("contradicts", 3, "b")]) == "inconclusive"
    assert pool([s("supports", 3, "a"), s("contradicts", 3, "b")])["assessment"] == "disputed"


def test_belief_lifecycle_audit_merge_split_restore(env):
    _, sf, _ = env
    s = sf()
    p = Project(name="x"); s.add(p); s.flush()
    be = BeliefEngine(s)
    b = be.create(p.id, "Method A improves performance", ["comparable datasets"])
    e1 = be.add_evidence(b.id, ev("g1"), "paper 1")
    be.add_evidence(b.id, ev("g2"), "paper 2")
    assert b.assessment == "supported" and b.version == 3
    be.add_evidence(b.id, ev("g3", "contradicts"), "paper 3")
    assert b.assessment == "disputed"
    hist = be.history(b.id)
    assert [h["action"] for h in hist] == ["create", "add_evidence", "add_evidence", "add_evidence"]
    assert all(h["reason"] for h in hist)
    # restore version 3 (before the contradicting paper) as a NEW version
    be.restore(b.id, 3, "test")
    assert b.assessment == "supported" and b.version == 5 and len(be.history(b.id)) == 5
    # merge / split
    b2 = be.create(p.id, "Method A is faster")
    be.add_evidence(b2.id, ev("g9"), "x")
    be.merge(b.id, b2.id, "same claim")
    assert s.get(type(b), b2.id).status == "merged"
    nb = be.split(b.id, [e1.id], "Method A improves performance (study 1 only)", "scope too broad")
    assert nb.id != b.id and nb.n_effective == 1
    be.mark_disputed(b.id, "reviewer"); assert b.status == "disputed"
    be.invalidate(b.id, "retraction"); assert b.status == "invalidated"
    s.commit()


def test_router_modes():
    assert route("perovskite solar cell degradation")["mode"] == "single"
    r = route("graphene battery for spacecraft in orbit")
    assert r["mode"] == "cross_domain" and set(r["domains"]) == {"technology", "space"}
    assert route("what's for dinner")["mode"] == "out_of_scope"
    assert route("we propose a hypothesis about the analysis of data")["mode"] == "unknown"


def test_plan_activates_only_needed_engines():
    feats = {"n_stats": 0, "n_equations": 0, "n_triples": 0, "n_causal": 0, "n_findings": 1}
    ids = {t.id for t in planner.build_plan(feats, {"domains": ["medicine"]})}
    assert not ids & {"stat_check", "math_check", "logic_check", "causal_audit"} and "acquire_medicine" in ids
    feats.update(n_stats=2, n_equations=1)
    ids = {t.id for t in planner.build_plan(feats, {"domains": []}, offline=True)}
    assert {"stat_check", "math_check"} <= ids and not any(i.startswith("acquire") for i in ids)


def test_executor_isolates_failures_and_replans():
    plan = [planner.Task("a", "boom"), planner.Task("b", "ok", deps=["a"]), planner.Task("c", "ok", optional_deps=["a"]),
            planner.Task("acq", "acquire_literature", params={"domain": "x"}), planner.Task("v", "ok", optional_deps=["acq"])]
    calls = []

    def acquire(ctx, t):
        calls.append(t.id)
        return {"n_papers": 0, "connectors": {"openalex": {"status": "ok"}}}

    h = {"boom": lambda c, t: 1 / 0, "ok": lambda c, t: {}, "acquire_literature": acquire}
    res = planner.execute(plan, h, None, on_complete=planner.replan_acquisition)
    assert res["a"]["status"] == "failed" and "ZeroDivisionError" in res["a"]["error"]
    assert res["b"]["status"] == "skipped" and res["c"]["status"] == "completed"
    assert calls == ["acq", "acq_retry1", "acq_retry2"] and res["v"]["status"] == "completed"
