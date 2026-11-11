"""Planner: builds a task DAG from document features and activates only needed engines. Includes replanning."""
from dataclasses import dataclass, field


@dataclass
class Task:
    id: str
    kind: str
    engine: str | None = None
    deps: list = field(default_factory=list)
    optional_deps: list = field(default_factory=list)
    params: dict = field(default_factory=dict)


def build_plan(features: dict, routing: dict, offline: bool = False, corpus_size: int = 0) -> list:
    t = []
    if features.get("n_stats"):
        t.append(Task("stat_check", "stat_check", "statistical_engine"))
    if features.get("n_equations"):
        t.append(Task("math_check", "math_check", "math_engine"))
    if features.get("n_triples", 0) >= 2:
        t.append(Task("logic_check", "logic_check", "logic_engine"))
    if features.get("n_causal"):
        t.append(Task("causal_audit", "causal_audit", "causal_engine"))
    acq = []
    if routing["domains"] and (not offline or corpus_size > 0) and features.get("n_findings"):
        for d in routing["domains"]:
            t.append(Task(f"acquire_{d}", "acquire_literature", params={"domain": d}))
            acq.append(f"acquire_{d}")
    t.append(Task("verify_evidence", "verify_evidence", optional_deps=acq))
    t.append(Task("belief_update", "belief_update", deps=["verify_evidence"], optional_deps=[x.id for x in t if x.kind in ("stat_check", "causal_audit")]))
    t.append(Task("graph_build", "graph_build", deps=["belief_update"]))
    t.append(Task("hypothesis_generate", "hypothesis_generate", deps=["graph_build"]))
    t.append(Task("hypothesis_verify", "hypothesis_verify", deps=["hypothesis_generate"]))
    t.append(Task("experiment_plan", "experiment_plan", deps=["hypothesis_verify"]))
    t.append(Task("report", "report", deps=["experiment_plan"], optional_deps=[x.id for x in t if x.kind in ("math_check", "logic_check")]))
    return t


def replan_acquisition(task, result: dict, max_retries: int = 2):
    """Dynamic replanning: if a domain search returned too little (and the source was reachable), broaden and retry."""
    if task.kind != "acquire_literature" or result["status"] not in ("completed", "partial"):
        return []
    out = result.get("output", {})
    level = task.params.get("broaden", 0)
    reachable = any(c.get("status") == "ok" for c in out.get("connectors", {}).values())
    if out.get("n_papers", 0) >= 2 or level >= max_retries or not reachable:
        return []
    return [Task(f"{task.id.split('_retry')[0]}_retry{level + 1}", "acquire_literature",
                 params={"domain": task.params["domain"], "broaden": level + 1})]


def execute(plan: list, handlers: dict, ctx, results: dict | None = None, on_complete=None) -> dict:
    """Topological execution. A failed task never aborts the run; dependents are skipped unless the dep is optional.
    `on_complete(task, result)` may return new tasks (replanning); pending tasks that waited on the parent also wait on them."""
    import time
    results = results if results is not None else {}
    pending = {t.id: t for t in plan}
    while pending:
        ready = [t for t in pending.values() if all(d in results for d in t.deps + t.optional_deps)]
        if not ready:
            for t in pending.values():
                results[t.id] = {"status": "skipped", "reason": "unsatisfiable dependencies"}
            break
        for t in ready:
            pending.pop(t.id)
            bad = [d for d in t.deps if results[d]["status"] not in ("completed", "partial")]
            if bad:
                results[t.id] = {"status": "skipped", "reason": f"required dependency failed: {bad}"}
                continue
            t0 = time.time()
            try:
                sess = getattr(ctx, "s", None)
                if sess is not None:   # each task runs in a SAVEPOINT: its DB error rolls back only its own writes
                    with sess.begin_nested():
                        out = handlers[t.kind](ctx, t) or {}
                else:
                    out = handlers[t.kind](ctx, t) or {}
                results[t.id] = {"status": out.pop("_status", "completed"), "output": out}
            except Exception as e:  # structured error, never silent
                results[t.id] = {"status": "failed", "error": f"{type(e).__name__}: {e}"}
            results[t.id]["duration_s"] = round(time.time() - t0, 4)
            results[t.id]["engine"] = t.engine
            if on_complete:
                for nt in on_complete(t, results[t.id]) or []:
                    pending[nt.id] = nt
                    for other in pending.values():
                        if t.id in other.optional_deps and nt.id not in other.optional_deps:
                            other.optional_deps.append(nt.id)
    return results
