import json
import re

import httpx
import networkx as nx
import pytest

from noesis.config import Settings
from noesis.graph import linkpred
from noesis.hypothesis import engine as hyp
from noesis.hypothesis import refine
from noesis.llm.client import LLMClient
from tests.conftest import make_pdf  # noqa: F401
from tests.test_llm import reply


def test_transe_learns_structure_and_refuses_tiny_graphs():
    heads, tails = [f"h{i}" for i in range(6)], [f"t{i}" for i in range(6)]
    triples = [(h, "increases", t) for h in heads for t in tails if (h, t) != ("h0", "t0")]      # hold out h0 -> t0
    m = linkpred.TransE(seed=1).fit(triples)
    assert m.rank_tail("h0", "increases", "t0") <= 6                                           # held-out true tail lands inside the tail cluster
    assert min(m.rank_tail("h0", "increases", h) for h in heads) >= 7                          # while no head is ever a plausible tail
    with pytest.raises(ValueError, match="need >="):
        linkpred.TransE().fit(triples[:5])
    G = nx.DiGraph()
    G.add_edge("entity:a", "entity:b", signs=[1]); G.add_edge("entity:b", "entity:c", signs=[1])
    assert linkpred.rank_candidates(G, [("entity:a", 1, "entity:c")]) == {}                  # small graph: no fake predictions


def chain_graph():
    E = nx.DiGraph()
    for n in "abc":
        E.add_node(f"entity:{n}", type="entity", label=n, domains=["technology"])
    E.add_edge("entity:a", "entity:b", sources=["claim:1"], signs=[1]); E.add_edge("entity:b", "entity:c", sources=["paper:2"], signs=[1])
    return E


def hyps():
    return hyp.generate(chain_graph(), [], ["unrelated"], "2026-11-06") + hyp.generate(_second(), [], ["unrelated"], "2026-11-06")


def _second():
    E = nx.DiGraph()
    for n in ("x", "y", "z"):
        E.add_node(f"entity:{n}", type="entity", label=n, domains=["technology"])
    E.add_edge("entity:x", "entity:y", sources=["claim:3"], signs=[1]); E.add_edge("entity:y", "entity:z", sources=["paper:4"], signs=[-1])
    return E


def llm_with(handler):
    return LLMClient(Settings(llm_api_key="k", offline=False), client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)


def test_hypotheses_record_link_prediction_status(env):
    h = hyp.generate(chain_graph(), [], [], "2026-11-06")[0]
    assert h["link_prediction"]["rank_among_tails"] is None and "too small" in h["link_prediction"]["note"]


def test_critic_loop_drops_revises_rejects_drift_and_ranks():
    hs = [dict(h, hypothesis_id=f"H{i}") for i, h in enumerate(hyps(), 1)][:2]
    for i, h in enumerate(hs):
        h["status"] = "candidate"
    a, b = hs

    def handler(req):
        u = json.loads(req.content)["messages"][0]["content"]
        if "skeptical reviewer" in u:
            stmt = re.search(r"<hypothesis>(.*)</hypothesis>", u).group(1)
            if a["statement"] == stmt:
                return reply({"verdict": "revise", "issue": "too strong", "revised_statement": "completely unrelated drifting statement", "score": 4})
            return reply({"verdict": "revise", "issue": "needs condition", "revised_statement": b["statement"] + " under dry conditions", "score": 2})
        return reply({"winner": "A"})

    info = refine.refine(llm_with(handler), hs)
    assert info["rejected_revisions"] == 1 and info["revised"] == 1 and info["tournament_pairs"] == 1
    assert a["statement"].startswith(a["variables"]["independent"]) and "revisions" not in a                  # drift rejected, original kept
    assert b["revisions"][0]["to"].endswith("under dry conditions") and b["critic"]["validated"] is False
    assert a["score_components"]["tournament_wins"] == 1 and b["score_components"]["tournament_wins"] == 0
    assert hs[0]["hypothesis_id"] == a["hypothesis_id"] and a["ranking"]["rank"] == 1                          # critic 4 + wins beat critic 2


def test_critic_drop_and_noop_without_llm():
    hs = hyps()[:2]
    for h in hs:
        h["status"] = "candidate"
    assert refine.refine(None, hs)["used"] is False and refine.refine(LLMClient(Settings(offline=False)), hs)["used"] is False
    info = refine.refine(llm_with(lambda r: reply({"verdict": "drop", "issue": "trivial", "score": 1, "winner": "A"})), hs)
    assert info["dropped"] == 2 and all(h["status"] == "dropped_by_critic" for h in hs)
