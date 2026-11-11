"""Hypothesis engine: candidates come from graph structure (gaps, contradictions, cross-domain chains), never from a bare prompt.

Ranking is Borda rank-sum over documented components - deliberately NO invented weights.
`confidence` stays None: no calibration data exists (Rule 8).
"""
from datetime import date

from ..graph import evidence_graph as eg
from ..graph import linkpred


def _ent(n: str) -> str:
    return n.split(":", 1)[1]


def novelty_check(a: str, c: str, corpus: list, today: str) -> dict:
    hits = [t[:140] for t in corpus if a in t.lower() and c in t.lower()]
    return {"corpus_size": len(corpus), "search_date": today, "method": "lexical co-occurrence of both entities in one text",
            "cooccurrences": len(hits), "examples": hits[:2],
            "verdict": "possibly_already_described" if hits else "no_cooccurrence_found_in_corpus",
            "limitation": "absence in a small, retrieval-limited corpus does NOT establish novelty; run a full literature search"}


def generate(E, beliefs: list, corpus: list, today: str | None = None, max_candidates: int = 10) -> list:
    today = today or date.today().isoformat()
    cands = []
    for g in eg.find_gaps(E, limit=max_candidates * 2):
        a, c, mids = _ent(g["a"]), _ent(g["c"]), [_ent(m) for m in g["mediators"]]
        doms = sorted((set(E.nodes[g["a"]].get("domains", [])) | set(E.nodes[g["c"]].get("domains", []))
                       | {d for m in g["mediators"] for d in E.nodes[m].get("domains", [])}) - {""})
        verb = "increase" if g["sign"] > 0 else "decrease"
        cands.append({
            "statement": f"{a} is predicted to {verb} {c}, mediated by {', '.join(mids)}.",
            "domain": doms, "method": "cross_domain_link" if len(doms) > 1 else "link_gap",
            "supporting_claims": g["sources"], "contradicting_claims": [],
            "scientific_gap": f"No source in the corpus directly links {a} to {c}; both are connected only via {', '.join(mids)}.",
            "assumptions": ["influence is transitive along the chain (not guaranteed)", "conditions are comparable across the source studies"],
            "mechanism": " -> ".join([a, mids[0], c]),
            "plausibility_assessment": {"basis": "signed path composition", "predicted_sign": g["sign"], "path": [a, mids[0], c]},
            "variables": {"independent": a, "dependent": c, "mediators": mids},
            "required_data": [f"measurements of {a} and {c} under the same conditions", f"measurement of {mids[0]} to test the mediation"],
            "_a": a, "_c": c, "_ev": len(set(g["sources"])), "_score": g["score"]})
    for ctr in eg.find_contradictions(E)[:max_candidates]:
        s_, o_ = _ent(ctr["subject"]), _ent(ctr["object"])
        cands.append({
            "statement": f"The effect of {s_} on {o_} depends on an unmeasured moderator that differs between the supporting and contradicting sources.",
            "domain": sorted(set(E.nodes[ctr["subject"]].get("domains", [])) - {""}), "method": "contradiction",
            "supporting_claims": [src for src, sg in zip(ctr["sources"], ctr["signs"]) if sg > 0],
            "contradicting_claims": [src for src, sg in zip(ctr["sources"], ctr["signs"]) if sg < 0],
            "scientific_gap": f"Sources disagree on the sign of the effect of {s_} on {o_}.",
            "assumptions": ["the disagreement is not due to measurement error or retracted/low-quality sources"],
            "mechanism": "unspecified moderator (condition, dose, composition, dataset, or protocol)",
            "plausibility_assessment": {"basis": "unresolved contradiction between sources"},
            "variables": {"independent": s_, "dependent": o_, "mediators": []},
            "required_data": [f"per-study conditions for the sources listed under supporting/contradicting claims"],
            "_a": s_, "_c": o_, "_ev": len(ctr["sources"]), "_score": 1.0})
    # TransE link prediction (only when the graph is big enough to train on)
    lp = linkpred.rank_candidates(E, [("entity:" + h["_a"], 1 if h["plausibility_assessment"].get("predicted_sign", 1) > 0 else -1, "entity:" + h["_c"]) for h in cands if h["method"] != "contradiction"])
    # novelty + testability, then Borda ranking
    for i, h in enumerate(cands):
        h["novelty_assessment"] = novelty_check(h["_a"], h["_c"], corpus, today)
        t = 0
        t += bool(h["variables"]["independent"] and h["variables"]["dependent"])
        t += h["plausibility_assessment"].get("predicted_sign") is not None or h["method"] == "contradiction"
        t += bool(h["required_data"])
        h["testability"] = {"checklist_score": t, "max": 3, "criteria": ["variables defined", "directional/refutable prediction", "required data identified"]}
        h["score_components"] = {"evidence_sources": h["_ev"], "novelty": 0 if h["novelty_assessment"]["cooccurrences"] else 1,
                                "testability": t}
        rk = lp.get(("entity:" + h["_a"], "entity:" + h["_c"]))
        h["link_prediction"] = {"method": "transe", "rank_among_tails": rk} if rk else {"method": "transe", "rank_among_tails": None, "note": "graph too small to train"}
    comps = ["evidence_sources", "novelty", "testability"]
    for comp in comps:
        order = sorted(cands, key=lambda h: -h["score_components"][comp])
        for r, h in enumerate(order):
            h.setdefault("_rank_sum", 0)
            h["_rank_sum"] += r
    cands.sort(key=lambda h: (h["_rank_sum"], -h["_score"]))
    out = []
    for i, h in enumerate(cands[:max_candidates], 1):
        out.append({
            "hypothesis_id": f"H{i:03d}", "statement": h["statement"], "domain": h["domain"], "generation_method": h["method"],
            "supporting_claims": h["supporting_claims"], "contradicting_claims": h["contradicting_claims"],
            "scientific_gap": h["scientific_gap"], "assumptions": h["assumptions"], "mechanism": h["mechanism"],
            "novelty_assessment": h["novelty_assessment"], "plausibility_assessment": h["plausibility_assessment"],
            "testability": h["testability"], "required_data": h["required_data"], "variables": h["variables"],
            "proposed_experiment": {}, "limitations": ["generated by structural graph analysis over a small corpus; unvalidated"],
            "score_components": h["score_components"], "link_prediction": h["link_prediction"], "ranking": {"method": "borda rank-sum, unweighted", "rank": i},
            "confidence": None, "status": "candidate"})
    return out


def verify(h: dict, E, beliefs: list) -> dict:
    checks = []
    nov = h["novelty_assessment"]
    already = nov["verdict"] == "possibly_already_described" and h.get("generation_method") != "contradiction"
    checks.append({"check": "existing_literature", "passed": not already,
                   "detail": nov["verdict"] if not h.get("generation_method") == "contradiction" else "n/a: the documented disagreement is itself the gap"})
    a, c = f"entity:{h['variables']['independent']}", f"entity:{h['variables']['dependent']}"
    conflict = False
    pred = h["plausibility_assessment"].get("predicted_sign")
    if pred is not None and a in E and c in E:
        for u, v in ((a, c), (c, a)):
            if E.has_edge(u, v) and u == a and (1 if sum(E[u][v]["signs"]) >= 0 else -1) != pred:
                conflict = True
    checks.append({"check": "conflict_with_existing_claims", "passed": not conflict, "detail": "direct opposite-sign edge exists" if conflict else "none found"})
    checks.append({"check": "assumptions_explicit", "passed": bool(h["assumptions"]), "detail": f"{len(h['assumptions'])} listed"})
    checks.append({"check": "evidence_based_motivation", "passed": bool(h["supporting_claims"]), "detail": f"{len(h['supporting_claims'])} source(s)"})
    checks.append({"check": "mechanism_stated", "passed": bool(h["mechanism"]), "detail": h["mechanism"][:80]})
    checks.append({"check": "testable", "passed": h["testability"]["checklist_score"] >= 2, "detail": f"{h['testability']['checklist_score']}/3"})
    if conflict:
        status = "conflicts_with_existing_evidence"
    elif already:
        status = "likely_already_described"
    else:
        status = "requires_validation"
    return {"checks": checks, "status": status,
            "not_checked": ["physical/biological constraint check (needs domain simulator/expert)", "full-literature novelty search"]}
