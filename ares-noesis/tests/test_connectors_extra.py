import json

import httpx
import pytest

from noesis.connectors import sources as S
from noesis.connectors.base import ConnectorError, ConnectorUnavailable, Paper
from tests.test_connectors_more import mk
from tests.test_query import Q, app_with, ask, paper

JATS = """<article><front/><body>
<sec><title>Introduction</title><p>Humidity degrades perovskite films.</p><p>We test <italic>this</italic> claim.</p></sec>
<sec><title>Results</title><p>Degradation rose by 12%.</p><table-wrap><table><tr><td>skip me</td></tr></table></table-wrap></sec>
</body></article>"""


def test_nih_reporter_posts_criteria_and_marks_records_as_grants():
    seen = {}

    def h(req):
        seen["body"] = json.loads(req.content)
        assert req.method == "POST"
        return httpx.Response(200, json={"results": [{"appl_id": 9, "project_title": "Perovskite stability", "abstract_text": "<p>Study of humidity.</p>",
                                                      "fiscal_year": 2022, "principal_investigators": [{"full_name": "Ana Lopez"}], "project_detail_url": "https://x/9"}]})
    p, = mk(S.NIHReporterConnector, h).search("perovskite humidity", 3, page=2)
    assert seen["body"]["criteria"]["advanced_text_search"]["search_text"] == "perovskite humidity" and seen["body"]["offset"] == 3 and seen["body"]["limit"] == 3
    assert p.pub_types == ["grant"] and p.abstract == "Study of humidity." and p.year == 2022 and p.authors == ["Ana Lopez"]


def test_patentsview_needs_a_key_and_sends_it():
    c = mk(S.PatentsViewConnector, lambda r: httpx.Response(200, json={}))
    assert c.available()[0] is False and "API key" in c.available()[1]
    with pytest.raises(ConnectorUnavailable):
        c.search("graphene")
    got = {}

    def h(req):
        got["key"] = req.headers["X-Api-Key"]
        got["q"] = json.loads(req.url.params["q"])
        return httpx.Response(200, json={"patents": [{"patent_id": "123", "patent_title": "Coated anode", "patent_abstract": "A graphene coating.",
                                                      "patent_date": "2021-03-02", "inventors": [{"inventor_name_first": "Cy", "inventor_name_last": "Dahl"}]}]})
    p, = mk(S.PatentsViewConnector, h, patentsview_api_key="K").search("graphene coating")
    assert got["key"] == "K" and "_text_any" in got["q"] and p.pub_types == ["patent"] and p.year == 2021 and p.authors == ["Cy Dahl"]


def test_datagov_parses_catalogue_records():
    def h(req):
        assert req.url.params["rows"] == "2"
        return httpx.Response(200, json={"result": {"results": [{"id": "d1", "name": "solar-data", "title": "Solar irradiance", "notes": "Hourly <b>data</b>.",
                                                                 "license_title": "CC0", "metadata_modified": "2023-05-01T00:00:00", "organization": {"title": "NREL"}}]}})
    p, = mk(S.DataGovConnector, h).search("solar", 2)
    assert p.pub_types == ["dataset"] and p.abstract == "Hourly data." and p.license == "CC0" and p.url.endswith("/solar-data") and p.year == 2023


def test_europepmc_full_text_sections_and_missing_article():
    def h(req):
        if "PMC404" in req.url.path:
            return httpx.Response(404)
        return httpx.Response(200, text=JATS)
    c = mk(S.EuropePMCConnector, h)
    secs = c.full_text("PMC1")
    assert [s["section"] for s in secs] == ["introduction", "results"]
    assert "We test this claim." in secs[0]["text"] and "skip me" not in secs[1]["text"]
    with pytest.raises(ConnectorError):
        c.full_text("PMC404")


def test_post_retries_then_reports_unavailable():
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(503)
    with pytest.raises(ConnectorUnavailable):
        mk(S.NIHReporterConnector, h).search("x")
    assert len(calls) == 4                                                    # 1 try + 3 retries


def test_grants_patents_datasets_never_count_as_evidence(env):
    settings, sf, _ = env
    grant = Paper(source="nih_reporter", title="Graphene coating lifespan project", abstract="We found that graphene coating increases battery lifespan.",
                  doi="10.1/g", authors=["Zed Grant"], pub_types=["grant"])
    patent = Paper(source="patentsview", title="Graphene coating patent", abstract="We found that graphene coating increases battery lifespan.",
                   doi="10.1/pt", authors=["Pat Ent"], pub_types=["patent"])
    c, pid = app_with(env, [grant, patent])
    m = ask(c, pid, Q)["result"]["coverage"][0]
    assert m["n_effective"] == 0 and m["status"] == "no_evidence"             # retrieved, but context only
