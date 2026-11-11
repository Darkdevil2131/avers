"""Logical engine: propositional consistency (SAT via SymPy) with minimal unsat core."""
from sympy import And, Implies, Not, Symbol
from sympy.logic.inference import satisfiable


def _build(facts: dict, rules: list):
    sym = {}

    def S(name):
        return sym.setdefault(name, Symbol(name))

    forms = {}
    for atom, val in facts.items():
        forms[f"fact:{atom}"] = S(atom) if val else Not(S(atom))
    for i, r in enumerate(rules):
        ante = And(*[S(a) for a in r["if"]]) if r["if"] else True
        then = r["then"]
        cons = Not(S(then[1:])) if then.startswith("~") else S(then)
        forms[f"rule:{i}"] = Implies(ante, cons)
    return forms


def check_consistency(facts: dict, rules: list) -> dict:
    forms = _build(facts, rules)
    if satisfiable(And(*forms.values())):
        return {"consistent": True, "core": []}
    core = list(forms)
    for k in list(forms):  # deletion-based minimal unsat core
        trial = [x for x in core if x != k]
        if trial and not satisfiable(And(*[forms[x] for x in trial])):
            core = trial
    return {"consistent": False, "core": core, "method": "SAT (sympy) + deletion-based minimal core"}


def run(task: dict) -> dict:
    if task.get("operation") == "check_consistency":
        return check_consistency(task.get("facts", {}), task.get("rules", []))
    raise ValueError("unknown operation")
