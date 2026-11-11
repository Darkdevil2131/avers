"""Evaluation metrics with bootstrap confidence intervals (so differences between systems are not over-claimed)."""
import numpy as np


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0, "tp": tp, "fp": fp, "fn": fn}


def classification_report(gold: list, pred: list, labels: list, n_boot: int = 1000, seed: int = 0) -> dict:
    g, p = np.asarray(gold), np.asarray(pred)

    def macro_f1(ix):
        fs = []
        for lab in labels:
            tp = int(((g[ix] == lab) & (p[ix] == lab)).sum()); fp = int(((g[ix] != lab) & (p[ix] == lab)).sum()); fn = int(((g[ix] == lab) & (p[ix] != lab)).sum())
            fs.append(prf(tp, fp, fn)["f1"])
        return float(np.mean(fs))

    idx = np.arange(len(g))
    rng = np.random.default_rng(seed)
    boots = [macro_f1(rng.choice(idx, len(idx))) for _ in range(n_boot)] if len(idx) else [0.0]
    per = {lab: prf(int(((g == lab) & (p == lab)).sum()), int(((g != lab) & (p == lab)).sum()), int(((g == lab) & (p != lab)).sum())) for lab in labels}
    return {"n": int(len(g)), "accuracy": round(float((g == p).mean()), 4) if len(g) else 0.0, "macro_f1": round(macro_f1(idx), 4) if len(g) else 0.0,
            "macro_f1_ci95": [round(float(np.percentile(boots, 2.5)), 4), round(float(np.percentile(boots, 97.5)), 4)], "per_class": per,
            "confusion": {a: {b: int(((g == a) & (p == b)).sum()) for b in labels} for a in labels}}
