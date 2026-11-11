"""Mathematical engine (SymPy). Untrusted input is whitelisted before parsing."""
import random
import re

import sympy as sp
from sympy.parsing.sympy_parser import convert_xor, parse_expr, standard_transformations

FUNCS = {n: getattr(sp, f) for n, f in {
    "sin": "sin", "cos": "cos", "tan": "tan", "exp": "exp", "log": "log", "ln": "log", "sqrt": "sqrt",
    "abs": "Abs", "asin": "asin", "acos": "acos", "atan": "atan", "sinh": "sinh", "cosh": "cosh", "tanh": "tanh"}.items()}
_SAFE = re.compile(r"^[A-Za-z0-9_+\-*/^().,\s]*$")
_GLOBALS = {"Integer": sp.Integer, "Float": sp.Float, "Rational": sp.Rational, "Symbol": sp.Symbol, "__builtins__": {}}


class UnsafeExpression(ValueError):
    pass


def parse_safe(s: str):
    if len(s) > 300 or not _SAFE.match(s) or "__" in s:
        raise UnsafeExpression("expression contains disallowed characters or is too long")
    names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", s))
    local = dict(FUNCS)
    local["pi"] = sp.pi
    for n in names:
        if n in local:
            continue
        if len(n) > 12:
            raise UnsafeExpression(f"identifier too long: {n[:20]}")
        local[n] = sp.Symbol(n)
    try:
        return parse_expr(s, local_dict=local, global_dict=dict(_GLOBALS),
                          transformations=standard_transformations + (convert_xor,))
    except Exception as e:
        raise ValueError(f"unparseable: {e}")


def split_equation(eq: str):
    parts = re.split(r"(?<![<>=!])=(?!=)", eq)
    if len(parts) != 2:
        raise ValueError("expected exactly one '='")
    return parts[0].strip(), parts[1].strip()


def check_identity(lhs: str, rhs: str, trials: int = 6) -> dict:
    try:
        diff = sp.simplify(parse_safe(lhs) - parse_safe(rhs))
    except UnsafeExpression:
        return {"verdict": "rejected_unsafe_input"}
    except ValueError as e:
        return {"verdict": "unparseable", "detail": str(e)}
    if diff == 0:
        return {"verdict": "identity", "method": "sympy.simplify(lhs-rhs)==0"}
    syms = sorted(diff.free_symbols, key=str)
    rng = random.Random(0)
    worst = 0.0
    for _ in range(trials):
        sub = {s: rng.uniform(0.5, 3.0) for s in syms}
        try:
            v = abs(complex(diff.subs(sub).evalf()))
        except Exception:
            return {"verdict": "inconclusive", "residual": str(diff)}
        worst = max(worst, v)
    if worst < 1e-9:
        return {"verdict": "numerically_identity", "method": "random-point residual < 1e-9 (not a proof)"}
    return {"verdict": "not_identity", "residual": str(diff),
            "note": "holds only for some values (a constraint/equation), not an algebraic identity; not necessarily an error"}


def equations_equivalent(eq1: str, eq2: str) -> dict:
    try:
        f = parse_safe(split_equation(eq1)[0]) - parse_safe(split_equation(eq1)[1])
        g = parse_safe(split_equation(eq2)[0]) - parse_safe(split_equation(eq2)[1])
    except (UnsafeExpression, ValueError) as e:
        return {"verdict": "unparseable", "detail": str(e)}
    ratio = sp.simplify(f / g) if g != 0 else None
    if ratio is not None and ratio.is_number and ratio != 0:
        return {"verdict": "equivalent", "method": "constant ratio of (lhs-rhs)"}
    for s in sorted(f.free_symbols & g.free_symbols, key=str):
        try:
            a, b = sp.solve(f, s), sp.solve(g, s)
        except Exception:
            continue
        if a and len(a) == len(b) and all(any(sp.simplify(x - y) == 0 for y in b) for x in a):
            return {"verdict": "equivalent", "method": f"same solution set for {s}"}
    return {"verdict": "not_shown_equivalent"}


def evaluate(expr: str, values: dict) -> dict:
    e = parse_safe(expr)
    sub = {sp.Symbol(k): v for k, v in values.items()}
    return {"value": float(e.subs(sub).evalf()), "method": "sympy.evalf"}


def run(task: dict) -> dict:
    op = task.get("operation")
    if op == "check_equations":
        res = []
        for eq in task["equations"]:
            try:
                l, r = split_equation(eq)
                res.append({"equation": eq, **check_identity(l, r)})
            except ValueError as e:
                res.append({"equation": eq, "verdict": "unparseable", "detail": str(e)})
        return {"results": res, "n_checked": len(res)}
    if op == "equivalent":
        return equations_equivalent(task["a"], task["b"])
    if op == "evaluate":
        return evaluate(task["expr"], task.get("values", {}))
    if op == "check_dimensions":
        return check_dimensions(task["lhs"], task["rhs"], task["units"])
    raise ValueError(f"unknown operation '{op}'")


# ---------------- dimensional analysis (physical-consistency check) ----------------
from sympy.physics import units as _u
from sympy.physics.units import Dimension as _Dim
from sympy.physics.units.systems.si import dimsys_SI as _dimsys

UNIT_NAMES = {n: getattr(_u, n) for n in ["m", "kg", "s", "A", "K", "mol", "cd", "N", "J", "W", "Pa", "Hz", "C", "V", "ohm", "T", "F", "H", "L",
                                          "g", "km", "cm", "mm", "hour", "minute", "day", "eV", "bar", "percent"] if hasattr(_u, n)}


class DimensionError(ValueError):
    pass


def _unit_dims(unit_str: str) -> dict:
    if not _SAFE.match(unit_str) or "__" in unit_str:
        raise UnsafeExpression("unit string has disallowed characters")
    names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", unit_str))
    bad = names - set(UNIT_NAMES)
    if bad:
        raise DimensionError(f"unknown unit(s): {sorted(bad)}")
    e = parse_expr(unit_str.replace("^", "**"), local_dict=dict(UNIT_NAMES), global_dict=dict(_GLOBALS),
                   transformations=standard_transformations)
    return _expr_dims(e, {})


def _clean(d: dict) -> dict:
    return {str(k.name): v for k, v in d.items() if v != 0}


def _expr_dims(e, symdims: dict) -> dict:
    from sympy.physics.units.quantities import Quantity
    if e.is_number:
        return {}
    if isinstance(e, sp.Symbol):
        if e.name not in symdims:
            raise DimensionError(f"no unit given for symbol '{e.name}'")
        return symdims[e.name]
    if isinstance(e, Quantity):
        return _clean(_dimsys.get_dimensional_dependencies(_Dim(SI_expr(e))))
    if e.is_Add:
        ds = [_expr_dims(t, symdims) for t in e.args]
        if any(d != ds[0] for d in ds):
            raise DimensionError(f"cannot add terms with different dimensions: {ds}")
        return ds[0]
    if e.is_Mul:
        out: dict = {}
        for t in e.args:
            for k, v in _expr_dims(t, symdims).items():
                out[k] = out.get(k, 0) + v
        return {k: v for k, v in out.items() if v != 0}
    if e.is_Pow:
        base, ex = e.args
        if _expr_dims(ex, symdims):
            raise DimensionError("exponent must be dimensionless")
        if not ex.is_number:
            if _expr_dims(base, symdims):
                raise DimensionError("variable exponent on a dimensional base")
            return {}
        return {k: v * ex for k, v in _expr_dims(base, symdims).items()}
    if e.func.__name__ in ("sin", "cos", "tan", "exp", "log", "asin", "acos", "atan", "sinh", "cosh", "tanh"):
        if _expr_dims(e.args[0], symdims):
            raise DimensionError(f"argument of {e.func.__name__} must be dimensionless")
        return {}
    if e.func.__name__ == "Abs":
        return _expr_dims(e.args[0], symdims)
    raise DimensionError(f"unsupported construct: {e.func.__name__}")


def SI_expr(q):
    from sympy.physics.units.systems.si import SI
    return SI.get_dimensional_expr(q)


def check_dimensions(lhs: str, rhs: str, units: dict) -> dict:
    """Both sides of an equation must have identical SI dimensions, sums must be homogeneous, transcendental arguments dimensionless.
    `units` maps each symbol to a unit string, e.g. {"F": "N", "m": "kg", "a": "m/s**2"}."""
    try:
        symdims = {k: _unit_dims(v) for k, v in units.items()}
        dl, dr = _expr_dims(parse_safe(lhs), symdims), _expr_dims(parse_safe(rhs), symdims)
    except UnsafeExpression:
        return {"verdict": "rejected_unsafe_input"}
    except DimensionError as e:
        return {"verdict": "dimensionally_inconsistent", "detail": str(e)}
    except ValueError as e:
        return {"verdict": "unparseable", "detail": str(e)}
    if dl == dr:
        plain = {k: (int(v) if v == int(v) else float(v)) for k, v in dl.items()}      # plain JSON numbers, never SymPy objects
        return {"verdict": "dimensionally_consistent", "dimensions": plain, "method": "SI base-dimension algebra (sympy.physics.units)"}
    return {"verdict": "dimensionally_inconsistent", "detail": f"lhs {dl} != rhs {dr}"}
