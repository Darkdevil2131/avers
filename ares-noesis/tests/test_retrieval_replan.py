from noesis.corpus.chunk import chunk_sentences
from noesis.corpus.rerank import bm25_scores, rerank_order
from noesis.ingestion.parse import Sentence
from noesis.query.pipeline import broaden
from tests.test_query import Q, SUPPORT_A, SUPPORT_B, app_with, ask, paper


def S(text, page=1, section="results"):
    return Sentence(page=page, section=section, text=text)


def test_chunks_respect_section_boundaries_and_cover_every_sentence():
    sents = [S(f"Sentence number {i} has exactly seven words here.", 1, "methods") for i in range(10)] + \
            [S(f"Result sentence {i} has exactly seven words here.", 2, "results") for i in range(6)]
    ch = chunk_sentences(sents, target_words=30, overlap=1)
    assert all(len({sents[j].section for j in range(c["first"], c["last"] + 1)}) == 1 for c in ch)       # never crosses a section
    covered = {j for c in ch for j in range(c["first"], c["last"] + 1)}
    assert covered == set(range(16))                                                                      # nothing dropped
    assert all(c["n_words"] <= 30 + 8 for c in ch)
    assert ch[1]["first"] <= ch[0]["last"]                                                                 # overlap inside a section
    assert [c["section"] for c in ch][0] == "methods" and ch[-1]["section"] == "results" and ch[-1]["page"] == 2
    assert chunk_sentences([]) == [] and len(chunk_sentences([S("One sentence.")])) == 1


def test_bm25_and_rrf_promote_exact_term_matches():
    docs = ["general overview of batteries and coatings", "graphene coating battery lifespan study", "unrelated topic about orbits"]
    sc = bm25_scores("graphene coating lifespan", docs)
    assert sc[1] > sc[0] > sc[2] or sc[1] > sc[2]
    order = rerank_order("graphene coating lifespan", docs)                  # first stage put the generic doc first
    assert order[0] == 1 and sorted(order) == [0, 1, 2]
    assert bm25_scores("x", []) == [] and rerank_order("x", ["only one"]) == [0]


def test_broaden_gives_each_side_of_the_claim_then_concepts():
    sd = {"statement": "graphene coating increases battery lifespan",
          "triple": {"subject": "graphene coating", "object": "battery lifespan", "relation": "increases"}}
    alts = broaden(sd, {"concepts": ["graphene coating", "battery lifespan", "cycle life"]})
    assert alts == ["graphene coating", "battery lifespan", "cycle life"]
    assert broaden({"statement": "x", "triple": None}, {"concepts": []}) == []


def test_replanning_runs_only_when_evidence_is_thin_and_is_recorded(env):
    c, pid = app_with(env, [SUPPORT_A])                                       # one supporting paper: below target, must replan
    job = ask(c, pid)
    plan = job["result"]["plans"][0]["rounds"]
    assert plan[0]["round"] == 0 and len(plan) >= 2 and plan[1]["reason"] == "evidence below target; query broadened"
    assert len(plan) <= 1 + env[0].max_replans                                # bounded
    e2 = app_with(env, [SUPPORT_B, paper("Third study", "We found that graphene coating increases battery lifespan in 12 cells.", "10.1/t", "Di Roy")])
    plan2 = ask(*e2)["result"]["plans"][0]["rounds"]
    assert len(plan2) == 1                                                    # three supports (A,B,t) already in the corpus: no replanning needed


def test_lineage_relabelled_when_later_rounds_reveal_shared_authorship(env):
    from noesis.belief.engine import BeliefEngine
    from noesis.models import Belief, EvidenceItem
    from noesis.verification.evidence import EvidenceInput
    _, sf, _ = env
    s = sf()
    be = BeliefEngine(s)
    b = be.create(1, "x increases y")
    for i, (doi, g) in enumerate([("10.1/a", "lineage:1"), ("10.1/b", "lineage:2")], start=1):
        be.add_evidence(b.id, EvidenceInput(title=f"p{i}", doi=doi, design="rct", stance="supports", independence_group=g, paper_id=i), "t")
    assert be.s.get(Belief, b.id).n_effective == 2
    be.relabel_groups(b.id, {1: "lineage:1", 2: "lineage:1"}, "same author found later")
    assert be.s.get(Belief, b.id).n_effective == 1                                # two papers, one research group -> counted once
    be.relabel_groups(b.id, {1: "lineage:1", 2: "lineage:1"}, "no-op")
    assert [e["action"] for e in be.history(b.id)].count("relabel_lineage") == 1  # unchanged mapping adds no version
    s.close()
