"""Phase-4 evaluation: every question in docs/mcp_evaluation.xml is solved through the MCP tools and compared with the stated answer."""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from tests.test_mcp_server import run

QA = [(q.findtext("question"), q.findtext("answer")) for q in ET.parse(Path(__file__).resolve().parents[1] / "docs" / "mcp_evaluation.xml").getroot().iter("qa_pair")]


def test_evaluation_file_is_well_formed():
    assert len(QA) == 10 and len({q for q, _ in QA}) == 10 and all(a and a.strip() for _, a in QA)


def test_every_evaluation_question_is_answerable_through_the_tools(env):
    async def sc(c, call):
        J = lambda r: json.loads(r[0])
        ans = []
        ans.append(str(J(await call("noesis_sample_size", effect_size_d=0.5))["n_per_group"] - J(await call("noesis_sample_size", effect_size_d=0.8))["n_per_group"]))
        m = J(await call("noesis_meta_analysis", effects=[0.2, 0.4, 0.6], standard_errors=[0.1, 0.1, 0.2], model="fixed"))
        ans.append(f"{m['pooled']:.2f}")
        impossible = 0
        for mean in ("5.18", "5.19", "5.20"):
            impossible += 0 if J(await call("noesis_check_grim", mean=mean, n=28))["possible"] else 1
        ans.append(str(impossible))
        u = {"F": "N", "m": "kg", "a": "m/s**2", "E": "J", "v": "m/s"}
        consistent = 0
        for l, r in (("F", "m*a"), ("E", "m*v"), ("E", "m*v**2/2")):
            consistent += J(await call("noesis_check_dimensions", lhs=l, rhs=r, units=u))["verdict"] == "dimensionally_consistent"
        ans.append(str(consistent))
        reps = [{"test": "t", "stat": "2.10", "df1": "28", "op": "=", "p": ".045"}, {"test": "t", "stat": "1.20", "df1": "28", "op": "=", "p": ".03"}, {"test": "t", "stat": "2.10", "df1": "28", "op": "=", "p": ".01"}]
        ans.append(str(sum(1 for r in J(await call("noesis_check_reported_statistics", reports=reps))["results"] if r["status"] != "consistent")))
        o = J(await call("noesis_simulate_orbit", position_m=[7.0e6, 0, 0], velocity_mps=[0, 7546, 0], duration_s=3000))
        ans.append(str(round(o["kepler_period_s"] / 60)))
        ans.append(f"{J(await call('noesis_meta_analysis', effects=[0.2, 0.4, 0.6], standard_errors=[0.1, 0.1, 0.2], model='random'))['tau2']:.3f}")
        ans.append(str(round(J(await call("noesis_meta_analysis", effects=[0.1, 0.9, 0.5, 1.3], standard_errors=[0.1] * 4, model="random"))["I2_percent"])))
        eqs = [("(a+b)^2", "a^2+2*a*b+b^2"), ("(a-b)^2", "a^2-b^2"), ("sin(x)^2+cos(x)^2", "1")]
        idents = 0
        for l, r in eqs:
            idents += J(await call("noesis_check_equation_identity", lhs=l, rhs=r))["results"][0]["verdict"] in ("identity", "numerically_identity")
        ans.append(str(idents))
        ans.append(str(J(await call("noesis_sample_size", effect_size_d=0.3, alpha=0.01, power=0.9))["n_per_group"]))
        return ans
    got = run(env, sc)
    assert got == [a for _, a in QA], list(zip(got, [a for _, a in QA]))
