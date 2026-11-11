"""Tests for the readiness-audit gap fixes: temporal + validation engines, lineage, domain coverage, directional seeds."""
from noesis.engines import registry
from noesis.engines.temporal_engine import stance_trend
from noesis.engines.validation_engine import validate_beliefs
from noesis.planning.router import route
from noesis.query.pipeline import seed_hypotheses, understand
from noesis.verification.lineage import lineage_groups


def pts(*pairs):
    return [{"year": y, "stance": s} for y, s in pairs]


def test_temporal_engine_detects_shift_and_refuses_thin_data():
    shifting = stance_trend(pts(*[(2010 + i, "contradicts") for i in range(6)], *[(2016 + i, "supports") for i in range(6)]))
    assert shifting["status"] == "ok" and shifting["trend"] == "shifting_toward_support" and shifting["p_value"] < 0.05
    assert stance_trend(pts((2020, "supports"), (2021, "supports")))["status"] == "insufficient_evidence"
    assert stance_trend(pts((2020, "supports"), (2020, "supports"), (2020, "contradicts"), (2020, "supports")))["status"] == "insufficient_evidence"   # one year only
    stable = stance_trend(pts((2018, "supports"), (2019, "supports"), (2020, "supports"), (2021, "supports")))
    assert stable["trend"] == "stable" and stable["tau"] is None
    assert "temporal_engine" in registry.profiles() and registry.engine_for("stance_trend") == "temporal_engine"


def test_validation_engine_flags_weak_beliefs_and_never_edits():
    beliefs = [{"hypothesis": "A increases B", "n_effective": 1, "status": "covered", "gate_passed": False, "designs": ["observational"]},
               {"hypothesis": "C increases D", "n_effective": 3, "status": "contradicted", "gate_passed": True, "designs": ["rct"]},
               {"hypothesis": "E increases F", "n_effective": 0, "status": "no_evidence", "gate_passed": False, "designs": []}]
    out = validate_beliefs(beliefs, "causal")
    codes = {(i["hypothesis"], i["code"]) for i in out["issues"]}
    assert ("A increases B", "single_independent_source") in codes
    assert ("A increases B", "causal_without_interventional_design") in codes
    assert ("C increases D", "gate_passed_but_contested") in codes and ("C increases D", "causal_without_interventional_design") not in codes
    assert ("E increases F", "no_independent_evidence") in codes
    assert beliefs[0]["n_effective"] == 1                                    # inputs untouched
    assert validate_beliefs(beliefs, "factual")["n_with_issues"] == 3
    assert not any(i["code"] == "causal_without_interventional_design" for i in validate_beliefs(beliefs, "factual")["issues"])


def test_lineage_groups_merge_shared_authors_and_ignore_bare_surnames():
    g = lineage_groups({1: ["Ana Lopez", "Cy Dahl"], 2: ["A. Lopez"], 3: ["Bo Chen"], 4: ["Lopez"], 5: []})
    assert g[1] == g[2]                      # same (initial, surname) -> one lineage
    assert g[3] != g[1] and g[4] != g[1]     # bare surname is too ambiguous to link; unrelated author stays separate
    assert g[5] != g[1] and g[5] != g[3]
    g2 = lineage_groups({1: ["Ana Lopez"], 2: ["Bo Chen", "Cy Dahl"], 3: ["Cy Dahl", "Di Roy"]})
    assert g2[2] == g2[3] and g2[1] != g2[2]


def test_router_covers_more_domains_and_unknown_falls_back_to_general():
    assert route("Do catalysts increase reaction yield in polymer synthesis?")["domains"][0] == "chemistry"
    assert route("How does ocean warming affect glacier loss and climate?")["domains"][0] == "earth_science"
    assert route("Is the conjecture implied by this theorem and lemma?")["domains"][0] == "mathematics"
    assert route("we propose a hypothesis about the analysis of data")["mode"] == "unknown"
    from noesis.agents.domain_agents import AGENT_CLASSES
    assert {"chemistry", "physics", "earth_science", "life_science", "social_science", "mathematics", "general"} <= set(AGENT_CLASSES)


def test_temporal_question_type_and_directional_pair_seeds():
    u = understand(None, "How has battery lifespan with graphene coating changed over time?")
    assert u["question_type"] == "temporal"
    u2 = {"question": "xyz", "concepts": ["graphene coating", "battery lifespan"], "question_type": "causal"}
    seeds = seed_hypotheses(None, {**u2, "question": "graphene coating and battery lifespan"})
    st = {s["statement"] for s in seeds}
    assert {"graphene coating increases battery lifespan", "graphene coating decreases battery lifespan"} <= st
    assert all(s["triple"] is not None for s in seeds)                      # both directions are testable, unlike "is related to"


def test_heartbeat_keeps_a_long_job_from_being_reclaimed(env):
    import time
    from datetime import datetime, timedelta, timezone
    from noesis import worker
    from noesis.models import Job
    settings, sf, store = env
    settings.lease_seconds = 1
    s = sf()
    j = worker.enqueue(s, 1, "query", {"question": "x"})
    jid = j.id
    s.close()
    spec = worker.claim(sf, settings, "w1")
    assert spec and spec[0] == jid
    with worker.Heartbeat(sf, settings, jid, interval=0.2):
        time.sleep(2.5)                                                   # longer than the 1 s lease
        assert worker.claim(sf, settings, "w2") is None                   # not re-claimed while the heartbeat runs
    s = sf()
    lease = s.get(Job, jid).lease_until
    s.close()
    time.sleep(1.3)                                                       # heartbeat stopped (worker "crashed"): lease must now expire
    assert worker.claim(sf, settings, "w2") is not None


def test_database_rejects_claims_without_text_and_evidence_without_source(env):
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import DatabaseError
    _, sf, _ = env
    s = sf()
    for sql, msg in [("insert into claims (document_id, text, page, section, kind, meta) values (1, '  ', 0, '', 'finding', '{}')", "no text"),
                     ("insert into evidence_items (belief_id, title, doi, stance, grade, grade_label, active) values (1, '', '', 'supports', 1, 'very_low', 1)", "no source")]:
        with pytest.raises(DatabaseError, match=msg):
            s.execute(text(sql))
        s.rollback()
    s.close()


def test_end_to_end_papers_sharing_an_author_count_once(env):
    from tests.test_query import Q, SUPPORT_A, app_with, ask, paper
    same_group = paper("Coated cells last longer", "We found that graphene coating increases battery lifespan across 40 coated cells.", "10.1/z", "Ana Lopez")
    c, pid = app_with(env, [SUPPORT_A, same_group])          # SUPPORT_A is also by Ana Lopez: one research group, two papers
    m = ask(c, pid, Q)["result"]["coverage"][0]
    assert m["n_effective"] == 1 and m["gate"]["passed"] is False      # before the fix these were two "independent" sources only when first authors differed
    c2, pid2 = app_with(env, [SUPPORT_A, paper("Coated cells last longer", "We found that graphene coating increases battery lifespan across 40 coated cells.", "10.1/y", "Cy Dahl")])
    assert ask(c2, pid2, Q)["result"]["coverage"][0]["n_effective"] == 2


def test_triple_object_stops_at_common_scope_words():
    from noesis.ingestion.claims import extract_triple
    for tail in ("across 40 coated cells", "among field samples", "over 500 cycles", "during storage", "within the pack", "for commercial cells", "after ageing"):
        t = extract_triple(f"We found that graphene coating increases battery lifespan {tail}.")
        assert t and t["object"] == "battery lifespan", (tail, t)
