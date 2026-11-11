"""Knowledge-validation engine: deterministic sanity checks on beliefs before they reach a report.

It never changes a belief. It lists issues with a code, a severity and a reason, so a reader (and the report) can see
where a conclusion is weaker than its wording suggests. No LLM, no scoring beyond the rules below."""
INTERVENTIONAL = {"rct", "meta_analysis", "systematic_review"}


def validate_beliefs(beliefs: list, question_type: str = "factual") -> dict:
    issues = []

    def add(b, code, sev, msg):
        issues.append({"hypothesis": b["hypothesis"], "code": code, "severity": sev, "message": msg})

    for b in beliefs:
        n = b.get("n_effective", 0)
        designs = [d or "unknown" for d in b.get("designs", [])]
        if n == 0:
            add(b, "no_independent_evidence", "high", "no independent supporting or opposing evidence was retrieved")
        elif n == 1:
            add(b, "single_independent_source", "medium", "rests on one independent lineage; a single source cannot corroborate itself")
        if designs and all(d == "unknown" for d in designs):
            add(b, "design_unknown", "medium", "study design could not be identified for any supporting item, so grades default to the lowest tier")
        if question_type == "causal" and designs and not (INTERVENTIONAL & set(designs)):
            add(b, "causal_without_interventional_design", "high", "causal question, but no supporting item is a randomized trial or systematic synthesis: treat as association")
        if b.get("gate_passed") and b.get("status") == "contradicted":
            add(b, "gate_passed_but_contested", "high", "passed the veracity gate while evidence also points against it")
    return {"n_beliefs": len(beliefs), "n_with_issues": len({i["hypothesis"] for i in issues}), "issues": issues,
            "method": "rule checks (deterministic)"}


def run(task: dict) -> dict:
    if task.get("operation") == "validate_beliefs":
        return validate_beliefs(task["beliefs"], task.get("question_type", "factual"))
    raise ValueError("unknown operation")
