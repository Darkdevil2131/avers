import httpx
import pytest

from noesis.agents.base import TaskMessage
from noesis.agents.domain_agents import build_agents
from noesis.config import Settings
from noesis.connectors import sources as S
from noesis.connectors.base import ConnectorUnavailable

PUBMED_XML = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>111</PMID><Article>
<Journal><Title>J Test Med</Title><JournalIssue><PubDate><Year>2021</Year></PubDate></JournalIssue></Journal>
<ArticleTitle>Metformin and <i>tumour</i> growth: a randomized trial</ArticleTitle>
<Abstract><AbstractText Label="BACKGROUND">Metformin reduces tumour growth.</AbstractText><AbstractText Label="RESULTS">Growth fell in 40 patients.</AbstractText></Abstract>
<AuthorList><Author><LastName>Lopez</LastName><ForeName>Ana</ForeName></Author></AuthorList>
<PublicationTypeList><PublicationType>Randomized Controlled Trial</PublicationType></PublicationTypeList></Article></MedlineCitation>
<PubmedData><ArticleIdList><ArticleId IdType="pubmed">111</ArticleId><ArticleId IdType="doi">10.1/pm1</ArticleId></ArticleIdList></PubmedData></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>222</PMID><Article><Journal><Title>J Old</Title><JournalIssue><PubDate><MedlineDate>2019 Jan-Feb</MedlineDate></PubDate></JournalIssue></Journal>
<ArticleTitle>Retracted claim</ArticleTitle><PublicationTypeList><PublicationType>Retracted Publication</PublicationType></PublicationTypeList></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""

CT = {"studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT01", "briefTitle": "Short", "officialTitle": "Metformin in cancer"},
      "descriptionModule": {"briefSummary": "Metformin reduces tumour growth."}, "statusModule": {"startDateStruct": {"date": "2020-05"}},
      "designModule": {"studyType": "INTERVENTIONAL", "designInfo": {"allocation": "RANDOMIZED"}, "enrollmentInfo": {"count": 120}}}},
      {"protocolSection": {"identificationModule": {"nctId": "NCT02", "briefTitle": "Obs"}, "designModule": {"studyType": "OBSERVATIONAL"}}}]}


def mk(cls, handler, **kw):
    c = cls(Settings(offline=False, **kw), client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    c.min_interval = 0
    return c


def test_pubmed_two_step_fetch_parses_abstract_types_retraction():
    seen = []

    def h(req):
        seen.append(req.url.path)
        if "esearch" in req.url.path:
            assert req.url.params["retstart"] == "0"
            return httpx.Response(200, json={"esearchresult": {"idlist": ["111", "222"]}})
        return httpx.Response(200, text=PUBMED_XML)

    a, b = mk(S.PubMedConnector, h).search("metformin cancer", 2)
    assert a.title == "Metformin and tumour growth: a randomized trial" and "Growth fell" in a.abstract and a.doi == "10.1/pm1"
    assert a.year == 2021 and a.authors == ["Ana Lopez"] and "Randomized Controlled Trial" in a.pub_types and a.retracted is None
    assert b.retracted is True and b.year == 2019 and any("efetch" in p for p in seen)


def test_pubmed_empty_result_and_api_key_forwarded():
    got = {}
    c = mk(S.PubMedConnector, lambda r: (got.update(r.url.params), httpx.Response(200, json={"esearchresult": {"idlist": []}}))[1], ncbi_api_key="K")
    assert c.search("zzz") == [] and got["api_key"] == "K"


def test_clinicaltrials_design_and_enrollment_are_structured():
    r, o = mk(S.ClinicalTrialsConnector, lambda q: httpx.Response(200, json=CT)).search("metformin")
    assert r.pub_types == ["Randomized Controlled Trial"] and r.sample_size == 120 and r.year == 2020 and r.license == "public domain"
    assert o.pub_types == ["Clinical Trial"] and o.sample_size is None
    assert mk(S.ClinicalTrialsConnector, lambda q: httpx.Response(200, json=CT)).search("x", page=2) == []


def test_semanticscholar_doaj_core_github_parsing_and_auth():
    s2 = {"data": [{"paperId": "abc", "title": "T", "abstract": "A", "year": 2020, "authors": [{"name": "X Y"}], "venue": "V", "externalIds": {"DOI": "10.1/s"},
                    "citationCount": 4, "openAccessPdf": {"url": "http://pdf"}, "publicationTypes": ["JournalArticle"]}, {"paperId": "n", "title": None, "externalIds": None}]}
    p = mk(S.SemanticScholarConnector, lambda r: httpx.Response(200, json=s2), s2_api_key="k").search("q")
    assert p[0].doi == "10.1/s" and p[0].open_access_pdf == "http://pdf" and p[1].title == ""        # tolerates null fields
    doaj = {"results": [{"id": "1", "bibjson": {"title": "OA", "abstract": "ab", "year": "2019", "author": [{"name": "Q"}], "journal": {"title": "J", "license": [{"type": "CC BY"}]},
                         "identifier": [{"type": "doi", "id": "10.1/d"}], "link": [{"url": "http://l"}]}}]}
    d = mk(S.DOAJConnector, lambda r: httpx.Response(200, json=doaj)).search("a b/c")[0]
    assert d.license == "CC BY" and d.doi == "10.1/d" and d.year == 2019
    with pytest.raises(ConnectorUnavailable, match="CORE_API_KEY"):
        S.COREConnector(Settings(offline=False)).search("x")
    core = {"results": [{"id": 9, "title": "C", "abstract": "ab", "doi": "10.1/c", "yearPublished": 2018, "authors": [{"name": "Z"}], "downloadUrl": "http://dl", "licenses": [{"type": "cc-by"}]}]}
    c = mk(S.COREConnector, lambda r: (httpx.Response(200, json=core) if r.headers["authorization"] == "Bearer K" else httpx.Response(401)), core_api_key="K").search("q")[0]
    assert c.license == "cc-by" and c.year == 2018
    gh = {"items": [{"full_name": "o/r", "description": "impl", "html_url": "http://g", "license": {"spdx_id": "MIT"}, "stargazers_count": 5}, {"full_name": "o/n", "license": None}]}
    g = mk(S.GitHubConnector, lambda r: httpx.Response(200, json=gh)).search("q")
    assert g[0].license == "MIT" and g[1].license == "" and g[0].pub_types == ["software"]


def test_agents_use_new_sources_and_github_is_separate_from_evidence():
    conns = {n: mk(c, lambda r: httpx.Response(200, json={"items": [{"full_name": "o/r", "license": {"spdx_id": "MIT"}}]}))
             for n, c in [("github", S.GitHubConnector)]}
    agents = build_agents(conns)
    assert "pubmed" in agents["medicine"].connector_names and "clinicaltrials" in agents["medicine"].connector_names
    assert "doaj" in agents["technology"].connector_names and "github" not in agents["technology"].connector_names
    res = agents["technology"].execute(TaskMessage(task_id="t", agent="technology_agent", objective="impl", inputs={"queries": ["graphene"]}, required_operations=["find_implementations"]))
    assert res.outputs["implementations"][0]["license"] == "MIT"
    assert agents["medicine"].execute(TaskMessage(task_id="t", agent="m", objective="x", required_operations=["find_implementations"])).status == "permission_denied"


def test_trial_sample_size_flows_into_evidence_grade(env):
    """A registry RCT with n=12 must be downgraded by the sample-size criterion."""
    from noesis.verification.evidence import EvidenceInput, assess
    assert assess(EvidenceInput(design="rct", sample_size=12, peer_reviewed=True))["grade"] == 3
    assert assess(EvidenceInput(design="rct", sample_size=120, peer_reviewed=True))["grade"] == 4
