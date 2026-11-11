import pytest

from noesis.engines import causal_engine, logic_engine, math_engine, stats_engine, registry


def test_pvalue_consistent_with_rounding():
    r = stats_engine.check_report("t", "2.10", "28", None, "=", "0.045")
    assert r["status"] == "consistent"


def test_pvalue_decision_error_detected():
    r = stats_engine.check_report("t", "1.20", "28", None, "=", ".03")
    assert r["status"] == "decision_error"
    assert r["computed_p_range"][0] > 0.2


def test_pvalue_inconsistent_minor():
    r = stats_engine.check_report("t", "2.10", "28", None, "=", ".01")
    assert r["status"] == "inconsistent"


def test_F_chi2_r_supported():
    assert stats_engine.check_report("F", "4.50", "1", "40", "=", "0.04")["status"] in ("consistent", "inconsistent")
    assert stats_engine.p_value("chi2", 3.84, 1) == pytest.approx(0.05, abs=1e-3)
    assert stats_engine.p_value("r", 0.45, 28) == pytest.approx(0.0135, abs=2e-3)


def test_less_than_reporting():
    assert stats_engine.check_report("t", "3.50", "28", None, "<", ".05")["status"] == "consistent"
    assert stats_engine.check_report("t", "1.00", "28", None, "<", ".05")["status"] == "decision_error"


def test_grim():
    assert stats_engine.grim("5.18", 28)["possible"] is True
    assert stats_engine.grim("5.19", 28)["possible"] is False


def test_sample_size_matches_reference():
    assert stats_engine.sample_size_two_sample_t(0.5) == 64
    assert stats_engine.power_two_sample_t(0.5, 64) >= 0.8


def test_math_identity_and_non_identity():
    assert math_engine.check_identity("(a+b)^2", "a^2+2*a*b+b^2")["verdict"] == "identity"
    assert math_engine.check_identity("sin(x)^2+cos(x)^2", "1")["verdict"] in ("identity", "numerically_identity")
    r = math_engine.check_identity("E", "m*c^2")
    assert r["verdict"] == "not_identity" and "not necessarily an error" in r["note"]


def test_math_rejects_code_injection():
    for bad in ["__import__('os').system('id')", "a; b", "open('/etc/passwd')", "x" * 400]:
        assert math_engine.check_identity(bad, "1")["verdict"] in ("rejected_unsafe_input", "unparseable")


def test_math_equivalent_and_evaluate():
    assert math_engine.equations_equivalent("F = m*a", "a = F/m")["verdict"] == "equivalent"
    assert math_engine.equations_equivalent("F = m*a", "F = m*a^2")["verdict"] == "not_shown_equivalent"
    assert math_engine.evaluate("m*a", {"m": 2, "a": 3})["value"] == 6.0


def test_logic_consistency_and_core():
    ok = logic_engine.check_consistency({"A": True}, [{"if": ["A"], "then": "B"}])
    assert ok["consistent"]
    bad = logic_engine.check_consistency({"A": True}, [{"if": ["A"], "then": "B"}, {"if": ["B"], "then": "~A"}])
    assert not bad["consistent"] and set(bad["core"]) == {"fact:A", "rule:0", "rule:1"}


def test_causal_backdoor():
    edges = [("Z", "X"), ("Z", "Y"), ("X", "Y")]
    assert causal_engine.backdoor_valid(edges, "X", "Y", ["Z"])["valid"]
    assert not causal_engine.backdoor_valid(edges, "X", "Y", [])["valid"]
    assert not causal_engine.backdoor_valid([("X", "M"), ("M", "Y")], "X", "Y", ["M"])["valid"]  # descendant


def test_causal_audit_flags_causal_wording_without_design():
    out = causal_engine.audit_causal_claims([{"language": "causal", "text": "A causes B", "page": 1}], "we observed data")
    assert len(out["flagged"]) == 1
    out = causal_engine.audit_causal_claims([{"language": "causal", "text": "A causes B", "page": 1}], "randomized trial")
    assert out["flagged"] == []


def test_registry_capability_lookup():
    assert registry.engine_for("grim") == "statistical_engine" and registry.engine_for("meta_analysis") == "statistical_engine"
    assert registry.engine_for("backdoor") == "causal_engine"
    assert registry.engine_for("teleport") is None
    assert "run" not in registry.profiles()["math_engine"]


def test_meta_analysis_matches_hand_calculation():
    fx = stats_engine.meta_analysis([0.3, 0.5, 0.4], [0.1, 0.1, 0.1], "fixed")
    assert fx["pooled"] == pytest.approx(0.4) and fx["se"] == pytest.approx(0.057735, abs=1e-5)
    assert fx["Q"] == pytest.approx(2.0) and fx["I2_percent"] == pytest.approx(0.0)     # (Q-df)/Q = 0 (clipped)
    het = stats_engine.meta_analysis([0.1, 0.9, 0.5, 1.3], [0.1, 0.1, 0.1, 0.1], "random")
    assert het["I2_percent"] > 90 and het["tau2"] > 0.2 and het["ci95"][0] < het["pooled"] < het["ci95"][1]
    with pytest.raises(ValueError):
        stats_engine.meta_analysis([0.3], [0.1])


def test_monte_carlo_agrees_with_analytic_power():
    r = stats_engine.simulate_power(0.5, 64, trials=6000, seed=1)
    assert r["simulated_power"] == pytest.approx(r["analytic_power"], abs=0.03)
