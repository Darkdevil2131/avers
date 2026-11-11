"""Statistical engine: recompute reported p-values (statcheck-style), GRIM, power/sample size.

All results are computed with SciPy; nothing here is LLM-generated.
Rounding of the reported statistic is accounted for (interval p-range), so correctly
rounded papers are not falsely flagged.
"""
import math
import re

from scipy import stats

ALPHA = 0.05


def _dec(s: str) -> int:
    return len(s.split(".")[1]) if "." in s else 0


def p_value(test: str, stat: float, df1: float, df2: float | None = None) -> float:
    s = abs(stat)
    if test == "t":
        return float(2 * stats.t.sf(s, df1))
    if test == "F":
        return float(stats.f.sf(s, df1, df2))
    if test == "chi2":
        return float(stats.chi2.sf(s, df1))
    if test == "r":
        r = min(s, 1 - 1e-12)
        t = r * math.sqrt(df1 / (1 - r * r))
        return float(2 * stats.t.sf(t, df1))
    raise ValueError(f"unsupported test '{test}'")


def check_report(test: str, stat: str, df1: str, df2: str | None, op: str, p: str) -> dict:
    d = _dec(stat)
    half = 0.5 * 10 ** -d
    s = abs(float(stat))
    lo, hi = max(s - half, 0.0), s + half
    f1 = float(df1)
    f2 = float(df2) if df2 else None
    p_hi, p_lo = p_value(test, lo, f1, f2), p_value(test, hi, f1, f2)
    p_mid = p_value(test, s, f1, f2)
    pr, dp = float(p), _dec(p)
    if op == "=":
        ok = round(p_lo, dp) - 1e-12 <= pr <= round(p_hi, dp) + 1e-12
        status = "consistent" if ok else "inconsistent"
    elif op == "<":
        status = "consistent" if p_hi < pr else ("borderline" if p_lo < pr else "inconsistent")
    else:
        status = "consistent" if p_lo > pr else ("borderline" if p_hi > pr else "inconsistent")
    reported_sig = op in ("<", "=") and pr <= ALPHA if op == "<" else (op == "=" and pr < ALPHA)
    straddles = p_lo < ALPHA <= p_hi
    gross = status == "inconsistent" and (reported_sig != (p_mid < ALPHA)) and not straddles
    return {
        "test": test, "reported": f"{test}({df1}{',' + df2 if df2 else ''})={stat}, p{op}{p}",
        "computed_p": round(p_mid, 6), "computed_p_range": [round(p_lo, 6), round(p_hi, 6)],
        "status": "decision_error" if gross else status,
        "method": "scipy.stats recompute with rounding-interval on reported statistic",
    }


def grim(mean_str: str, n: int) -> dict:
    """GRIM: can a mean reported to d decimals arise from n integer-valued observations?"""
    d, m = _dec(mean_str), float(mean_str)
    base = int(m * n)
    ok = any(abs(t / n - m) <= 0.5 * 10 ** -d + 1e-9 for t in range(base - 2, base + 3))
    return {"mean": mean_str, "n": n, "possible": ok, "method": "GRIM (Brown & Heathers) for integer data"}


def grim_table(rows: list) -> dict:
    """Run GRIM on every row of a table that has a 'mean' column and an integer 'n' column."""
    hdr = [h.lower().strip() for h in rows[0]]
    mi = next((i for i, h in enumerate(hdr) if h in ("mean", "m", "average")), None)
    ni = next((i for i, h in enumerate(hdr) if h in ("n", "sample size", "count")), None)
    if mi is None or ni is None:
        return {"applicable": False, "results": []}
    out = []
    for r in rows[1:]:
        try:
            if r[ni].strip().isdigit() and re.fullmatch(r"-?\d+\.\d+", r[mi].strip()):
                out.append({"row": r, **grim(r[mi].strip(), int(r[ni]))})
        except IndexError:
            continue
    return {"applicable": True, "results": out, "n_impossible": sum(1 for x in out if not x["possible"])}


def power_two_sample_t(d: float, n_per_group: int, alpha: float = ALPHA) -> float:
    df = 2 * n_per_group - 2
    nc = d * math.sqrt(n_per_group / 2)
    tcrit = stats.t.ppf(1 - alpha / 2, df)
    return float(1 - stats.nct.cdf(tcrit, df, nc) + stats.nct.cdf(-tcrit, df, nc))


def sample_size_two_sample_t(d: float, alpha: float = ALPHA, power: float = 0.8) -> int:
    if d <= 0:
        raise ValueError("effect size must be > 0")
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    approx = max(2, int(2 * (z / d) ** 2))
    for n in range(max(2, approx - 10), approx + 500):
        if power_two_sample_t(d, n, alpha) >= power:
            return n
    raise RuntimeError("sample size search failed")


def cohens_d_from_t(t: float, n1: int, n2: int) -> float:
    return float(t * math.sqrt(1 / n1 + 1 / n2))


def meta_analysis(effects: list, ses: list, model: str = "random") -> dict:
    """Inverse-variance pooling. model='fixed' or 'random' (DerSimonian-Laird). Returns pooled effect, 95% CI, Q, I2, tau2."""
    import numpy as np
    y, se = np.asarray(effects, float), np.asarray(ses, float)
    if len(y) < 2 or len(y) != len(se) or (se <= 0).any():
        raise ValueError("need >=2 effects with matching positive standard errors")
    w = 1 / se ** 2
    fixed = float((w * y).sum() / w.sum())
    q = float((w * (y - fixed) ** 2).sum())
    k = len(y)
    c = float(w.sum() - (w ** 2).sum() / w.sum())
    tau2 = max(0.0, (q - (k - 1)) / c) if c > 0 else 0.0
    i2 = max(0.0, (q - (k - 1)) / q) * 100 if q > 0 else 0.0
    wr = 1 / (se ** 2 + (tau2 if model == "random" else 0.0))
    pooled = float((wr * y).sum() / wr.sum())
    pse = float(1 / math.sqrt(wr.sum()))
    z = pooled / pse
    return {"model": model, "k": k, "pooled": round(pooled, 6), "se": round(pse, 6),
            "ci95": [round(pooled - 1.959964 * pse, 6), round(pooled + 1.959964 * pse, 6)],
            "p": float(2 * stats.norm.sf(abs(z))), "Q": round(q, 6), "Q_p": float(stats.chi2.sf(q, k - 1)),
            "I2_percent": round(i2, 2), "tau2": round(tau2, 6), "method": "inverse-variance, DerSimonian-Laird tau2"}


def simulate_power(d: float, n_per_group: int, trials: int = 4000, seed: int = 0, alpha: float = ALPHA) -> dict:
    """Monte Carlo check: how often would a two-group experiment with true effect d and n per group reach p<alpha?"""
    import numpy as np
    rng = np.random.default_rng(seed)
    a = rng.normal(0, 1, (trials, n_per_group))
    b = rng.normal(d, 1, (trials, n_per_group))
    p = stats.ttest_ind(a, b, axis=1).pvalue
    return {"simulated_power": float((p < alpha).mean()), "trials": trials, "analytic_power": power_two_sample_t(d, n_per_group, alpha),
            "method": "Monte Carlo two-sample t-test"}


def run(task: dict) -> dict:
    """Engine entrypoint: {"operation": ..., params}."""
    op = task.get("operation")
    if op == "check_reports":
        res = [check_report(r["test"], r["stat"], r["df1"], r.get("df2"), r["op"], r["p"]) for r in task["reports"]]
        bad = [r for r in res if r["status"] in ("inconsistent", "decision_error")]
        return {"results": res, "n_checked": len(res), "n_problems": len(bad)}
    if op == "grim_table":
        return grim_table(task["rows"])
    if op == "grim":
        return grim(task["mean"], int(task["n"]))
    if op == "sample_size":
        return {"n_per_group": sample_size_two_sample_t(float(task["d"]), task.get("alpha", ALPHA), task.get("power", 0.8))}
    if op == "meta_analysis":
        return meta_analysis(task["effects"], task["ses"], task.get("model", "random"))
    if op == "simulate_power":
        return simulate_power(float(task["d"]), int(task["n_per_group"]), int(task.get("trials", 4000)), int(task.get("seed", 0)))
    raise ValueError(f"unknown operation '{op}'")
