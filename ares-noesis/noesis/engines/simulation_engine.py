"""Simulation engine: only runs models with explicit governing equations, initial conditions and recorded parameters.
No 'simulate anything' fallback: unsupported problems are refused with a reason.
Operations: ode (user/paper-supplied equations), two_body (Newtonian orbital propagation with conservation checks)."""
import math

import numpy as np
import scipy
import sympy as sp
from scipy.integrate import solve_ivp

from .math_engine import UnsafeExpression, parse_safe

MU_EARTH = 3.986004418e14  # m^3/s^2 (standard gravitational parameter)


def _provenance(**kw):
    return {"scipy": scipy.__version__, "numpy": np.__version__, "sympy": sp.__version__, **kw}


def ode(equations: dict, y0: dict, t_span: list, params: dict | None = None, n_points: int = 50, rtol: float = 1e-8) -> dict:
    """equations: {"x": "-k*x"} meaning dx/dt = -k*x. Independent variable is `t`."""
    params = params or {}
    names = list(equations)
    if set(y0) != set(names):
        return {"status": "refused", "reason": "initial conditions must be given for exactly the state variables"}
    if not (len(t_span) == 2 and t_span[1] > t_span[0]):
        return {"status": "refused", "reason": "t_span must be [t0, t1] with t1 > t0"}
    syms = {n: sp.Symbol(n) for n in names + list(params) + ["t"]}
    try:
        rhs = [parse_safe(equations[n]) for n in names]
    except (UnsafeExpression, ValueError) as e:
        return {"status": "refused", "reason": f"equation rejected: {e}"}
    free = set().union(*[r.free_symbols for r in rhs]) - set(syms.values())
    if free:
        return {"status": "refused", "reason": f"unspecified symbols: {sorted(map(str, free))} (give them in params)"}
    f = sp.lambdify([syms["t"], [syms[n] for n in names]] + [syms[p] for p in params], rhs, modules="numpy")
    pv = [params[p] for p in params]
    sol = solve_ivp(lambda t, y: f(t, y, *pv), t_span, [y0[n] for n in names], method="RK45", rtol=rtol, atol=1e-12,
                    t_eval=np.linspace(t_span[0], t_span[1], n_points))
    if not sol.success:
        return {"status": "failed", "reason": sol.message}
    return {"status": "ok", "t": sol.t.tolist(), "y": {n: sol.y[i].tolist() for i, n in enumerate(names)},
            "provenance": _provenance(method="RK45", rtol=rtol, equations=equations, params=params, y0=y0),
            "assumptions": ["equations are taken as given (not validated against the source physics)"]}


def two_body(r0: list, v0: list, t_end: float, mu: float = MU_EARTH, n_points: int = 200) -> dict:
    r0, v0 = np.asarray(r0, float), np.asarray(v0, float)
    if r0.shape != (3,) or v0.shape != (3,) or np.linalg.norm(r0) <= 0 or t_end <= 0:
        return {"status": "refused", "reason": "need 3-vectors r0 (m), v0 (m/s), nonzero |r0| and t_end > 0"}

    def rhs(t, y):
        r = y[:3]
        return np.concatenate([y[3:], -mu * r / np.linalg.norm(r) ** 3])

    sol = solve_ivp(rhs, [0, t_end], np.concatenate([r0, v0]), method="DOP853", rtol=1e-11, atol=1e-9, t_eval=np.linspace(0, t_end, n_points))
    if not sol.success:
        return {"status": "failed", "reason": sol.message}
    r, v = sol.y[:3].T, sol.y[3:].T
    eps = 0.5 * (v ** 2).sum(1) - mu / np.linalg.norm(r, axis=1)
    h = np.cross(r, v)
    e_drift = float(abs((eps - eps[0]) / eps[0]).max())
    h_drift = float((np.linalg.norm(h - h[0], axis=1) / np.linalg.norm(h[0])).max())
    a = -mu / (2 * eps[0]) if eps[0] < 0 else None
    out = {"status": "ok", "bound_orbit": a is not None, "energy_rel_drift": e_drift, "angular_momentum_rel_drift": h_drift,
           "conserved": bool(e_drift < 1e-6 and h_drift < 1e-6), "final_r_m": r[-1].tolist(), "final_v_mps": v[-1].tolist(),
           "provenance": _provenance(method="DOP853", rtol=1e-11, mu=mu),
           "assumptions": ["point masses, Newtonian gravity only (no drag, J2, third bodies, radiation pressure)"]}
    if a:
        out["semi_major_axis_m"] = float(a)
        out["kepler_period_s"] = float(2 * math.pi * math.sqrt(a ** 3 / mu))
    return out


def run(task: dict) -> dict:
    op = task.get("operation")
    if op == "ode":
        return ode(task["equations"], task["y0"], task["t_span"], task.get("params"), int(task.get("n_points", 50)))
    if op == "two_body":
        return two_body(task["r0"], task["v0"], float(task["t_end"]), float(task.get("mu", MU_EARTH)), int(task.get("n_points", 200)))
    raise ValueError(f"unknown operation '{op}'; supported: ode, two_body. Other physics needs a validated external simulator.")
