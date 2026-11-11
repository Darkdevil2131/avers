"""Query-mode engine routing (Layer 6 for questions).

The query path used to retrieve, grade and report without ever calling a reasoning engine.
This module routes the retrieved evidence through the exact engines that apply to the question type and
returns one auditable record per engine run. Every record says what went in, what came out, or why the engine
could not run. Silence is never an option: an engine with no extractable input reports `not_applicable`.

Honest limits: inputs come from titles and abstracts only. Meta-analysis needs effect sizes that abstracts rarely
carry, so it is reported as not_applicable here rather than guessed.
"""
import re

from ..engines import registry
from ..ingestion.claims import extract_stats, language_of, triples_contradict

ROUTES = {
    "factual": ["statistical_engine", "logic_engine"],
    "comparative": ["statistical_engine", "logic_engine"],
    "causal": ["causal_engine", "statistical_engine", "logic_engine"],
    "exploratory": ["logic_engine"],
    "temporal": ["temporal_engine", "statistical_engine", "logic_engine"],
}
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


def _sentences(text: str) -> list:
    return [s.strip() for s in _SENT.split(text or "") if s.strip()]


def _run(engine: str, inputs: dict, n_inputs: int, fn) -> dict:
    if n_inputs == 0:
        return {"engine": engine, "status": "not_applicable", "n_inputs": 0,
                "reason": "no extractable input in the retrieved titles and abstracts"}
    try:
        out = fn()
    except Exception as e:                                  # an engine failure must be visible, never swallowed
        return {"engine": engine, "status": "failed", "n_inputs": n_inputs, "reason": f"{type(e).__name__}: {e}"}
    return {"engine": engine, "status": "ok", "n_inputs": n_inputs, "result": out}


def route_engines(question_type: str, papers: list, points_by_hyp: dict | None = None, beliefs: list | None = None) -> list:
    """papers: CorpusPaper-like rows (title, abstract, meta). points_by_hyp: {hypothesis: [{year, stance}]}. beliefs: validation inputs.
    Returns a list of engine-run records."""
    wanted = ROUTES.get(question_type, ROUTES["factual"])
    texts = [(p, f"{p.title}. {p.abstract or ''}") for p in papers]
    runs = []
    for eng in wanted:
        if eng == "statistical_engine":
            reps = [r for _, t in texts for s in _sentences(t) for r in extract_stats(s)]
            runs.append(_run(eng, {}, len(reps), lambda: registry.ENGINES[eng]["run"]({"operation": "check_reports", "reports": reps})))
        elif eng == "causal_engine":
            claims, intervention_text = [], " ".join(t for _, t in texts)
            for p, t in texts:
                for s in _sentences(t):
                    if language_of(s) == "causal":
                        claims.append({"text": s, "language": "causal", "page": None, "paper": p.title[:80]})
            runs.append(_run(eng, {}, len(claims), lambda: registry.ENGINES[eng]["run"](
                {"operation": "audit", "claims": claims, "document_text": intervention_text})))
        elif eng == "logic_engine":
            tr = [t for p, _ in texts for t in ((p.meta or {}).get("triples") or [])]
            pairs = [f"“{a['subject']} {a['relation']} {a['object']}” vs “{b['subject']} {b['relation']} {b['object']}”"
                     for i, a in enumerate(tr) for b in tr[i + 1:] if triples_contradict(a, b)]
            runs.append(_run(eng, {}, len(tr), lambda: {"n_contradictions": len(pairs), "pairs": pairs[:20],
                                                        "method": "triple-level contradiction check (heuristic)"}))
        elif eng == "temporal_engine":
            for hyp, pts in (points_by_hyp or {}).items():
                r = _run(eng, {}, len(pts), lambda: registry.ENGINES[eng]["run"]({"operation": "stance_trend", "points": pts}))
                runs.append({**r, "hypothesis": hyp})
            if not points_by_hyp:
                runs.append(_run(eng, {}, 0, None))
    # knowledge validation runs for every question type: it checks the beliefs the other engines feed
    runs.append(_run("validation_engine", {}, len(beliefs or []), lambda: registry.ENGINES["validation_engine"]["run"](
        {"operation": "validate_beliefs", "beliefs": beliefs, "question_type": question_type})))
    runs.append({"engine": "mathematical/simulation", "status": "not_applicable", "n_inputs": 0,
                 "reason": "not routed in query mode: needs equations or an explicit model, which abstracts do not reliably carry"})
    return runs
