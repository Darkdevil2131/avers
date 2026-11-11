import math

import pytest

from noesis.engines import math_engine as M, registry, simulation_engine as S


def test_ode_matches_analytic_solution_and_records_provenance():
    r = S.ode({"x": "-k*x"}, {"x": 2.0}, [0, 3], {"k": 0.7}, n_points=7)
    assert r["status"] == "ok"
    for t, x in zip(r["t"], r["y"]["x"]):
        assert x == pytest.approx(2.0 * math.exp(-0.7 * t), rel=1e-6)
    assert r["provenance"]["params"] == {"k": 0.7} and "scipy" in r["provenance"] and r["assumptions"]


def test_ode_coupled_system_and_refusals():
    r = S.ode({"x": "v", "v": "-w**2*x"}, {"x": 1.0, "v": 0.0}, [0, math.pi], {"w": 2.0}, n_points=3)
    assert r["y"]["x"][-1] == pytest.approx(math.cos(2 * math.pi), abs=1e-5)          # harmonic oscillator: full cycles
    assert S.ode({"x": "-k*x"}, {"x": 1}, [0, 1])["status"] == "refused"                # k unspecified
    assert S.ode({"x": "__import__('os')"}, {"x": 1}, [0, 1])["status"] == "refused"
    assert S.ode({"x": "-x"}, {"y": 1}, [0, 1])["status"] == "refused"
    assert S.ode({"x": "-x"}, {"x": 1}, [1, 0])["status"] == "refused"


def test_two_body_conserves_energy_and_matches_kepler_period():
    r0, v0 = [7.0e6, 0, 0], [0, 7.546e3, 0]                                             # roughly circular LEO
    a_circ = 7.0e6
    T = 2 * math.pi * math.sqrt(a_circ ** 3 / S.MU_EARTH)
    r = S.two_body(r0, v0, T)
    assert r["status"] == "ok" and r["conserved"] and r["bound_orbit"]
    assert r["kepler_period_s"] == pytest.approx(T, rel=2e-3)
    assert r["final_r_m"][0] == pytest.approx(7.0e6, rel=2e-3) and abs(r["final_r_m"][1]) < 3e4    # back near the start after one period
    hyper = S.two_body(r0, [0, 12e3, 0], 1000)
    assert hyper["bound_orbit"] is False and "kepler_period_s" not in hyper
    assert S.two_body([0, 0, 0], v0, 10)["status"] == "refused"
    assert "point masses" in r["assumptions"][0]


def test_unsupported_physics_is_refused_not_faked():
    with pytest.raises(ValueError, match="validated external simulator"):
        S.run({"operation": "quantum_molecular_dynamics"})
    assert registry.engine_for("two_body") == "simulation_engine"


def test_dimensional_analysis():
    u = {"F": "N", "m": "kg", "a": "m/s**2", "E": "J", "v": "m/s", "t": "s", "x": "m"}
    assert M.check_dimensions("F", "m*a", u)["verdict"] == "dimensionally_consistent"
    assert M.check_dimensions("E", "m*v**2/2", u)["verdict"] == "dimensionally_consistent"
    bad = M.check_dimensions("E", "m*v", u)
    assert bad["verdict"] == "dimensionally_inconsistent" and "!=" in bad["detail"]
    assert M.check_dimensions("x", "v*t + a*t", u)["verdict"] == "dimensionally_inconsistent"       # a*t is velocity, not length
    assert M.check_dimensions("x", "v*t + a*t**2/2", u)["verdict"] == "dimensionally_consistent"
    assert "dimensionless" in M.check_dimensions("x", "sin(t)", u)["detail"]
    assert "no unit given" in M.check_dimensions("x", "q*t", u)["detail"]
    assert M.check_dimensions("x", "m", {"x": "bogus"})["verdict"] == "dimensionally_inconsistent"
    assert M.check_dimensions("x", "m", {"x": "__import__('os')"})["verdict"] == "rejected_unsafe_input"
    assert M.run({"operation": "check_dimensions", "lhs": "F", "rhs": "m*a", "units": u})["verdict"] == "dimensionally_consistent"
