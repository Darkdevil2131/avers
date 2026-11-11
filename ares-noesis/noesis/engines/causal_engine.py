"""Causal engine: (1) audit causal wording vs study design, (2) backdoor-criterion check on a DAG."""
import re

import networkx as nx
import numpy as np

INTERVENTION = re.compile(r"\b(randomi[sz]ed|randomly assigned|intervention|controlled trial|knockout|ablation|we manipulated|instrumental variable)\b", re.I)


def audit_causal_claims(claims: list, document_text: str) -> dict:
    has_intervention = bool(INTERVENTION.search(document_text))
    flagged = []
    for c in claims:
        if c.get("language") == "causal" and not has_intervention:
            flagged.append({"claim": c["text"], "page": c.get("page"),
                            "issue": "causal wording without any interventional/randomized design cue in the document"})
    return {"n_causal_claims": sum(1 for c in claims if c.get("language") == "causal"),
            "document_has_intervention_cue": has_intervention, "flagged": flagged,
            "method": "lexical cue audit (heuristic); not a causal identification result"}


def backdoor_valid(edges: list, treatment: str, outcome: str, adjustment: list) -> dict:
    g = nx.DiGraph(edges)
    if not nx.is_directed_acyclic_graph(g):
        return {"valid": False, "reason": "graph has a cycle"}
    for n in (treatment, outcome, *adjustment):
        if n not in g:
            return {"valid": False, "reason": f"unknown node {n}"}
    desc = nx.descendants(g, treatment)
    if set(adjustment) & desc:
        return {"valid": False, "reason": "adjustment set contains a descendant of treatment"}
    g2 = g.copy()
    g2.remove_edges_from(list(g.out_edges(treatment)))
    ok = nx.is_d_separator(g2, {treatment}, {outcome}, set(adjustment))
    return {"valid": bool(ok), "reason": "backdoor paths blocked" if ok else "open backdoor path remains",
            "method": "backdoor criterion via d-separation (networkx)"}


def _ols(X, y):
    beta, _, rank, _ = np.linalg.lstsq(X, y, rcond=None)
    return beta, rank


def estimate_effect(data: dict, treatment: str, outcome: str, adjustment: list, edges: list | None = None,
                    n_boot: int = 300, seed: int = 0) -> dict:
    """Average effect of `treatment` on `outcome` by linear (OLS) backdoor adjustment, with a bootstrap 95% interval.

    Returns the adjusted effect AND the naive unadjusted one, so a reader can see how much confounding was removed. It is valid only if the
    adjustment set blocks every backdoor path and the effect is roughly linear and additive: both are stated in `assumptions`. If `edges`
    (a causal graph) are given, the backdoor criterion is checked first and estimation is refused when it fails. Data must be real observations."""
    cols = [treatment, outcome, *adjustment]
    miss = [c for c in cols if c not in data]
    if miss:
        return {"status": "failed", "reason": f"unknown column(s): {', '.join(miss)}"}
    n = len(data[treatment])
    if any(len(data[c]) != n for c in cols):
        return {"status": "failed", "reason": "columns have different lengths"}
    if n < 20 + 5 * len(adjustment):
        return {"status": "insufficient_evidence", "reason": f"{n} rows is too few for {len(adjustment)} adjustment variable(s) (need >= {20 + 5 * len(adjustment)})"}
    graph_check = None
    if edges is not None:
        graph_check = backdoor_valid(edges, treatment, outcome, adjustment)
        if not graph_check["valid"]:
            return {"status": "failed", "reason": graph_check["reason"], "graph_check": graph_check}
    try:
        t = np.asarray(data[treatment], dtype=float)
        y = np.asarray(data[outcome], dtype=float)
        Z = np.column_stack([np.asarray(data[c], dtype=float) for c in adjustment]) if adjustment else np.empty((n, 0))
    except (TypeError, ValueError):
        return {"status": "failed", "reason": "non-numeric data"}
    if not (np.isfinite(t).all() and np.isfinite(y).all() and np.isfinite(Z).all()):
        return {"status": "failed", "reason": "missing or non-finite values: clean the data first"}
    if np.ptp(t) == 0:
        return {"status": "failed", "reason": "treatment does not vary"}
    X = np.column_stack([np.ones(n), t, Z])
    beta, rank = _ols(X, y)
    if rank < X.shape[1]:
        return {"status": "failed", "reason": "adjustment variables are collinear with each other or the treatment"}
    naive, _ = _ols(np.column_stack([np.ones(n), t]), y)
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        i = rng.integers(0, n, n)
        b, rk = _ols(X[i], y[i])
        if rk == X.shape[1]:
            boots.append(b[1])
    lo, hi = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))) if len(boots) >= 20 else (None, None)
    return {"status": "ok", "effect": float(beta[1]), "ci95": [lo, hi], "naive_effect": float(naive[1]), "n": n, "adjustment": list(adjustment),
            "graph_check": graph_check, "seed": seed, "n_boot": len(boots),
            "method": "OLS backdoor adjustment (linear, additive; percentile bootstrap)",
            "assumptions": ["the adjustment set blocks all backdoor paths (no unmeasured confounding)", "effect is approximately linear and additive",
                            "observations are independent", "treatment precedes outcome"]}


def run(task: dict) -> dict:
    op = task.get("operation")
    if op == "audit":
        return audit_causal_claims(task["claims"], task.get("document_text", ""))
    if op == "backdoor":
        return backdoor_valid(task["edges"], task["treatment"], task["outcome"], task.get("adjustment", []))
    if op == "estimate_effect":
        return estimate_effect(task["data"], task["treatment"], task["outcome"], task.get("adjustment", []), task.get("edges"),
                               task.get("n_boot", 300), task.get("seed", 0))
    raise ValueError("unknown operation")
