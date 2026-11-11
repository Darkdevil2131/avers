"""Generate -> critique -> rank loop (Co-Scientist style), LLM-optional.
The critic may drop or revise a hypothesis; revisions must keep the original variables (no drift). Pairwise tournament
wins are an LLM opinion and are recorded as an UNVALIDATED component. Without an LLM key this module is a no-op."""
import itertools
import re

from ..llm import extract as llmx


def critique(llm, h: dict) -> dict | None:
    user = ('Act as a skeptical reviewer of this hypothesis. JSON only: {"verdict":"keep|revise|drop","issue":"<one sentence>",'
            '"revised_statement":"<only if revise; must mention the same two variables>","score":1}  (score 1-5 = scientific plausibility given only the listed support)\n'
            f"<hypothesis>{h['statement']}</hypothesis><support>{h['supporting_claims']}</support><gap>{h['scientific_gap']}</gap>")
    d, err = llmx.safe(lambda: llm.complete_json(llmx.SYSTEM, user, max_tokens=400))
    return d if isinstance(d, dict) else None


def _keeps_variables(h: dict, new: str) -> bool:
    n = new.lower()
    return all(re.search(r"\b" + re.escape(h["variables"][k].lower()) + r"\b", n) for k in ("independent", "dependent"))


def refine(llm, hyps: list, tournament_max: int = 6) -> dict:
    info = {"used": False, "dropped": 0, "revised": 0, "rejected_revisions": 0, "tournament_pairs": 0}
    if llm is None or not llm.available() or not hyps:
        return info
    info["used"] = True
    for h in hyps:
        c = critique(llm, h)
        if not c:
            continue
        verdict = c.get("verdict")
        score = c.get("score") if isinstance(c.get("score"), (int, float)) and 1 <= c["score"] <= 5 else None
        h["score_components"]["critic_score"] = score
        h["critic"] = {"verdict": verdict, "issue": str(c.get("issue", ""))[:300], "method": "llm_critic_v1", "validated": False}
        if verdict == "drop":
            h["status"] = "dropped_by_critic"
            info["dropped"] += 1
        elif verdict == "revise" and c.get("revised_statement"):
            new = str(c["revised_statement"])[:400]
            if _keeps_variables(h, new):
                h.setdefault("revisions", []).append({"from": h["statement"], "to": new, "reason": h["critic"]["issue"]})
                h["statement"] = new
                info["revised"] += 1
            else:
                info["rejected_revisions"] += 1
    alive = [h for h in hyps if h["status"] != "dropped_by_critic"][:tournament_max]
    wins = {h["hypothesis_id"]: 0 for h in alive}
    for a, b in itertools.combinations(alive, 2):
        d, err = llmx.safe(lambda: llm.complete_json(
            llmx.SYSTEM, 'Which hypothesis is better supported AND more testable? JSON only: {"winner":"A|B"}\n'
            f"<A>{a['statement']}</A><B>{b['statement']}</B>", max_tokens=60))
        if isinstance(d, dict) and d.get("winner") in ("A", "B"):
            wins[(a if d["winner"] == "A" else b)["hypothesis_id"]] += 1
            info["tournament_pairs"] += 1
    for h in alive:
        h["score_components"]["tournament_wins"] = wins[h["hypothesis_id"]]
    # re-rank: critic score and tournament wins join the unweighted Borda sum with the structural components
    comps = [c for c in ("evidence_sources", "novelty", "testability", "critic_score", "tournament_wins") if all(h["score_components"].get(c) is not None for h in alive)]
    for h in alive:
        h["_rs"] = 0
    for c in comps:
        for r, h in enumerate(sorted(alive, key=lambda x: -x["score_components"][c])):
            h["_rs"] += r
    alive.sort(key=lambda x: x["_rs"])
    for i, h in enumerate(alive, 1):
        h["ranking"] = {"method": f"borda rank-sum, unweighted, components={comps}", "rank": i}
        h.pop("_rs", None)
    hyps.sort(key=lambda h: (h["status"] == "dropped_by_critic", h["ranking"]["rank"]))
    return info
