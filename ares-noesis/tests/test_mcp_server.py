import asyncio
import json
import os
import re
import sys
from pathlib import Path

import httpx
import pytest
from mcp.client import Client

from noesis.api.main import create_app
from tests.conftest import TEST_KEY
from noesis.corpus import store as corpus
from noesis.mcp_server.client import NoesisClient
from noesis.mcp_server.server import create_server
from tests.test_query import OPPOSE, SUPPORT_A, SUPPORT_B

PAPER_TXT = """Graphene coating improves battery lifespan
Abstract
We found that graphene coating increases battery lifespan by 15% (t(28) = 2.10, p = .045).
Results
Humidity reduces electrolyte stability significantly (t(28) = 1.20, p = .03). Ion migration causes interface degradation.
Encapsulation reduces moisture damage.
Limitations
We did not test other chemistries.
References
[1] Smith et al. Coatings. doi:10.1000/xyz123.
"""


def run(env, scenario, papers=(), api_key=TEST_KEY, client_key=TEST_KEY):
    settings, sf, store = env
    settings.offline, settings.api_key = True, api_key
    s = sf()
    corpus.upsert(s, list(papers), "technology", "seed")
    s.commit()
    app = create_app(settings, sf, store, connectors={})
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://noesis.test")
    nc = NoesisClient("http://noesis.test", api_key=client_key, http=http)

    async def main():
        async with Client(create_server(nc)) as c:
            async def call(tool, /, **args):
                r = await c.call_tool(tool, {"params": args} if args else {})
                return r.content[0].text, r.is_error
            return await scenario(c, call)
    return asyncio.run(main())


def test_tool_catalogue_is_well_formed(env):
    async def sc(c, call):
        tools = (await c.list_tools()).tools
        names = [t.name for t in tools]
        assert len(names) == len(set(names)) == 24 and all(n.startswith("noesis_") for n in names)
        for t in tools:
            assert t.description and len(t.description) > 30 and t.annotations is not None, t.name
            assert t.annotations.destructive_hint is False and t.annotations.read_only_hint is not None
        ro = {t.name for t in tools if t.annotations.read_only_hint}
        assert {"noesis_get_beliefs", "noesis_get_report", "noesis_meta_analysis", "noesis_search_corpus"} <= ro
        assert not ro & {"noesis_create_project", "noesis_ask_question", "noesis_analyze_document", "noesis_submit_belief_feedback", "noesis_start_corpus_harvest"}
        assert next(t for t in tools if t.name == "noesis_start_corpus_harvest").annotations.open_world_hint is True
    run(env, sc)


def test_full_paper_workflow_through_mcp(env):
    async def sc(c, call):
        assert "Created project 1" in (await call("noesis_create_project", name="MCP test"))[0]
        up, err = await call("noesis_upload_text_document", project_id=1, filename="paper.txt", text=PAPER_TXT)
        assert not err and "document 1" in up
        started, _ = await call("noesis_analyze_document", project_id=1, document_id=1)
        job_id = int(re.search(r"job (\d+)", started).group(1))
        done, _ = await call("noesis_wait_for_job", job_id=job_id, timeout_seconds=20)
        assert "completed" in done and "report=completed" in done
        # pagination metadata on a list tool
        page, _ = await call("noesis_get_claims", project_id=1, limit=2, offset=0)
        assert re.search(r"\d+ claims \(showing 2 from offset 0; has_more=True, next_offset=2\)", page)
        last = json.loads((await call("noesis_get_claims", project_id=1, limit=50, offset=0, response_format="json", kind="limitation"))[0])
        assert last["total"] >= 1 and last["has_more"] is False and last["items"][0]["kind"] == "limitation"
        beliefs, _ = await call("noesis_get_beliefs", project_id=1)
        assert "inconsistent" in beliefs and "uncalibrated" in beliefs                       # flagged statistic + honesty about posterior
        bj = json.loads((await call("noesis_get_beliefs", project_id=1, response_format="json", limit=1))[0])
        assert bj["count"] == 1 and bj["has_more"] is True
        rep, _ = await call("noesis_get_report", project_id=1, max_chars=1000)
        assert rep.startswith("# Noesis Scientific Report") and "[truncated at 1000 characters" in rep
        bid = bj["items"][0]["id"]
        fb, _ = await call("noesis_submit_belief_feedback", belief_id=bid, action="invalidate", reason="reviewer rejected the method")
        assert "status=invalidated" in fb
        hist, _ = await call("noesis_get_belief_history", belief_id=bid)
        assert "reviewer rejected the method" in hist
    run(env, sc)


def test_ask_question_with_corpus_and_veracity_gate(env):
    async def sc(c, call):
        await call("noesis_create_project", name="Q")
        started, _ = await call("noesis_ask_question", project_id=1, question="Does graphene coating increase battery lifespan?")
        jid = int(re.search(r"job (\d+)", started).group(1))
        done, _ = await call("noesis_wait_for_job", job_id=jid, timeout_seconds=20)
        assert "Coverage:" in done and "graphene coating increases battery lifespan" in done and ("passed" in done or "WITHHELD" in done)
        rep, _ = await call("noesis_get_report", project_id=1)
        assert "## 3. Coverage matrix" in rep and "Graphene coating hurts lifespan" in rep
        hyp, _ = await call("noesis_list_hypotheses", project_id=1)
        assert "hypotheses" in hyp
        srch, _ = await call("noesis_search_corpus", query="graphene battery lifespan", limit=2)
        assert "Graphene" in srch and "license:cc-by" in srch
        stats, _ = await call("noesis_corpus_stats")
        assert '"total": 3' in stats
    run(env, sc, papers=[SUPPORT_A, SUPPORT_B, OPPOSE])


def test_engine_tools_return_exact_results(env):
    async def sc(c, call):
        assert json.loads((await call("noesis_sample_size", effect_size_d=0.5))[0])["n_per_group"] == 64
        m = json.loads((await call("noesis_meta_analysis", effects=[0.3, 0.5, 0.4], standard_errors=[0.1, 0.1, 0.1], model="fixed"))[0])
        assert m["pooled"] == pytest.approx(0.4) and m["k"] == 3
        assert json.loads((await call("noesis_check_grim", mean="5.19", n=28))[0])["possible"] is False
        d = json.loads((await call("noesis_check_dimensions", lhs="E", rhs="m*v", units={"E": "J", "m": "kg", "v": "m/s"}))[0])
        assert d["verdict"] == "dimensionally_inconsistent"
        s = json.loads((await call("noesis_check_reported_statistics", reports=[{"test": "t", "stat": "1.20", "df1": "28", "op": "=", "p": ".03"}]))[0])
        assert s["n_problems"] == 1 and s["results"][0]["status"] == "decision_error"
        e = json.loads((await call("noesis_check_equation_identity", lhs="(a+b)^2", rhs="a^2+2*a*b+b^2"))[0])
        assert e["results"][0]["verdict"] == "identity"
        o = json.loads((await call("noesis_simulate_orbit", position_m=[7.0e6, 0, 0], velocity_mps=[0, 7546, 0], duration_s=3000))[0])
        assert o["conserved"] is True and "point masses" in o["assumptions"][0]
        eng, _ = await call("noesis_list_engines")
        assert "simulation_engine" in eng
    run(env, sc)


def test_errors_are_actionable_not_stack_traces(env):
    async def sc(c, call):
        txt, err = await call("noesis_get_beliefs", project_id=999)
        assert "Not found" in txt and "noesis_list_projects" in txt
        txt, err = await call("noesis_sample_size", effect_size_d=-1)
        assert err is True and "validation error" in txt.lower()                           # schema rejects before any network call
        txt, err = await call("noesis_upload_text_document", project_id=1, filename="../evil.txt", text="x" * 60)
        assert err is True
        await call("noesis_create_project", name="x")
        await call("noesis_upload_text_document", project_id=1, filename="p.txt", text=PAPER_TXT)
        txt, _ = await call("noesis_upload_text_document", project_id=1, filename="p.txt", text=PAPER_TXT)
        assert "already existed" in txt
        txt, err = await call("noesis_check_dimensions", lhs="x", rhs="m", units={"x": "bogus"})
        assert "dimensionally_inconsistent" in txt
    run(env, sc)


def test_auth_failure_message_tells_agent_what_to_configure(env):
    async def sc(c, call):
        txt, _ = await call("noesis_list_projects")
        assert "Authentication failed" in txt and "NOESIS_TOKEN" in txt and "NOESIS_API_KEY" in txt
    run(env, sc, api_key=TEST_KEY, client_key="")

    async def sc2(c, call):
        txt, _ = await call("noesis_list_projects")
        assert "No projects yet" in txt
    run(env, sc2, api_key=TEST_KEY, client_key=TEST_KEY)


def test_unreachable_server_message():
    async def main():
        nc = NoesisClient("http://127.0.0.1:1", token="", api_key="")
        async with Client(create_server(nc)) as c:
            r = await c.call_tool("noesis_list_projects", {})
            return r.content[0].text
    assert "Cannot reach Noesis" in asyncio.run(main()) and "NOESIS_URL" in asyncio.run(main())


def test_double_analyze_conflict_points_to_existing_job(env):
    async def sc(c, call):
        await call("noesis_create_project", name="x")
        await call("noesis_upload_text_document", project_id=1, filename="p.txt", text=PAPER_TXT)
        env[0].queue_mode = "db"                                                         # keep job queued so the second call collides
        await call("noesis_analyze_document", project_id=1, document_id=1)
        txt, _ = await call("noesis_analyze_document", project_id=1, document_id=1)
        assert "already being analysed" in txt and "noesis_get_job" in txt
    run(env, sc)


def test_server_boots_over_stdio_in_a_real_subprocess():
    """The shipped entrypoint (python -m noesis.mcp_server) must speak MCP over stdio."""
    from mcp.client import Client
    from mcp.client.stdio import StdioServerParameters
    root = str(Path(__file__).resolve().parents[1])

    async def main():
        params = StdioServerParameters(command=sys.executable, args=["-m", "noesis.mcp_server"], env={**os.environ, "PYTHONPATH": root, "NOESIS_URL": "http://127.0.0.1:1"}, cwd="/tmp")
        async with Client(params) as c:
            names = [t.name for t in (await c.list_tools()).tools]
            r = await c.call_tool("noesis_list_projects", {})
            return names, r.content[0].text
    names, txt = asyncio.run(main())
    assert len(names) == 24 and "Cannot reach Noesis" in txt
