"""Temporal engine: is the direction of the evidence changing over time?

Input: dated evidence points {"year": int, "stance": "supports"|"contradicts"}. Method: Kendall rank correlation (SciPy)
between publication year and stance (+1/-1). It needs real dates and at least MIN_POINTS dated, stance-bearing items from at least
two distinct years; otherwise it says `insufficient_evidence` and gives no trend. Nothing is extrapolated."""
from scipy import stats

MIN_POINTS = 4
ALPHA = 0.05


def stance_trend(points: list) -> dict:
    pts = sorted((int(p["year"]), 1 if p["stance"] == "supports" else -1) for p in points
                 if p.get("year") and p.get("stance") in ("supports", "contradicts"))
    n = len(pts)
    base = {"n": n, "years": [pts[0][0], pts[-1][0]] if pts else None, "method": "Kendall tau between year and stance (+1/-1), SciPy"}
    if n < MIN_POINTS or len({y for y, _ in pts}) < 2:
        return {**base, "status": "insufficient_evidence", "reason": f"needs >= {MIN_POINTS} dated stance points across >= 2 years"}
    ys, ss = [y for y, _ in pts], [s for _, s in pts]
    if len(set(ss)) == 1:
        return {**base, "status": "ok", "trend": "stable", "detail": f"all {n} dated items {'support' if ss[0] > 0 else 'contradict'}", "tau": None, "p_value": None}
    tau, p = stats.kendalltau(ys, ss)
    tau, p = float(tau), float(p)
    if p >= ALPHA:
        trend = "no_significant_trend"
    else:
        trend = "shifting_toward_support" if tau > 0 else "shifting_toward_contradiction"
    return {**base, "status": "ok", "trend": trend, "tau": round(tau, 4), "p_value": round(p, 4),
            "caveat": "small samples have low power; a non-significant trend is not evidence of stability"}


def run(task: dict) -> dict:
    if task.get("operation") == "stance_trend":
        return stance_trend(task["points"])
    raise ValueError("unknown operation")
