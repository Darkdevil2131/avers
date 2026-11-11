import numpy as np
import pytest

from noesis.engines import registry
from noesis.engines.causal_engine import estimate_effect, run


def confounded(n=2000, seed=1, effect=2.0):
    r = np.random.default_rng(seed)
    z = r.normal(size=n)                          # confounder: raises both treatment and outcome
    t = 0.8 * z + r.normal(size=n)
    y = effect * t + 3.0 * z + r.normal(size=n)
    return {"T": t.tolist(), "Y": y.tolist(), "Z": z.tolist()}


def test_adjustment_recovers_the_true_effect_where_the_naive_estimate_is_biased():
    d = confounded()
    out = estimate_effect(d, "T", "Y", ["Z"], seed=0)
    assert out["status"] == "ok"
    assert abs(out["effect"] - 2.0) < 0.1 and out["ci95"][0] < 2.0 < out["ci95"][1]
    assert out["naive_effect"] > 2.8                                         # confounding inflates the unadjusted estimate
    assert out["n"] == 2000 and "linear" in out["method"] and out["assumptions"]


def test_estimate_is_reproducible_for_a_seed_and_refuses_bad_input():
    d = confounded(n=300)
    assert estimate_effect(d, "T", "Y", ["Z"], seed=3) == estimate_effect(d, "T", "Y", ["Z"], seed=3)
    assert estimate_effect(d, "T", "Y", ["Z"], seed=3)["ci95"] != estimate_effect(d, "T", "Y", ["Z"], seed=4)["ci95"]
    assert estimate_effect({"T": [1, 2, 3], "Y": [1, 2, 3]}, "T", "Y", [])["status"] == "insufficient_evidence"        # too few rows
    assert estimate_effect(d, "T", "nope", ["Z"])["status"] == "failed"
    dup = {**d, "Z2": d["Z"]}
    assert estimate_effect(dup, "T", "Y", ["Z", "Z2"])["status"] == "failed"                                          # collinear adjustment set
    assert estimate_effect({"T": [1.0] * 50, "Y": list(range(50))}, "T", "Y", [])["status"] == "failed"              # treatment never varies


def test_graph_check_blocks_estimation_when_a_backdoor_path_is_open():
    d = confounded(n=300)
    edges = [("Z", "T"), ("Z", "Y"), ("T", "Y")]
    bad = estimate_effect(d, "T", "Y", [], edges=edges)
    assert bad["status"] == "failed" and "open backdoor" in bad["reason"] and "effect" not in bad
    good = estimate_effect(d, "T", "Y", ["Z"], edges=edges)
    assert good["status"] == "ok" and good["graph_check"]["valid"] is True


def test_registered_and_callable_through_the_engine_contract():
    assert registry.engine_for("estimate_effect") == "causal_engine"
    out = run({"operation": "estimate_effect", "data": confounded(n=300), "treatment": "T", "outcome": "Y", "adjustment": ["Z"], "seed": 0})
    assert out["status"] == "ok"
