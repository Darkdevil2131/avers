import httpx
from sqlalchemy import select

from noesis.api.main import create_app
from noesis.config import Settings
from noesis.connectors.base import Paper
from noesis.connectors.sources import OpenAlexConnector
from noesis.corpus import store
from noesis.corpus.index import CorpusIndex
from noesis.models import CorpusPaper, SyncRun
from tests.conftest import authenticated_client, inv
from tests.test_api_e2e import _run
from tests.conftest import authenticated_client, make_pdf


def P(title, abstract, doi, **kw):
    return Paper(source="openalex", title=title, abstract=abstract, doi=doi, authors=["Ana Lopez"], license="cc-by", year=2022, **kw)


def test_upsert_dedupes_keeps_provenance_and_skips_empty(env):
    _, sf, _ = env
    s = sf()
    a = P("Graphene coating and lifespan", "We found that graphene coating increases battery lifespan.", "10.1/a")
    assert store.upsert(s, [a, a, P("", "x", "10.1/z"), P("No abstract no doi", "", "")], "technology", "t1") == 1
    assert store.upsert(s, [a], "technology", "t2") == 0
    row = s.scalars(select(CorpusPaper)).one()
    assert row.topics == ["t1", "t2"] and row.license == "cc-by" and row.domain == "technology"
    assert row.triples[0]["subject"] == "graphene coating"


def test_sync_pages_records_runs_and_survives_failures(env):
    _, sf, _ = env
    pages = []

    def handler(req):
        pg = int(req.url.params["page"]); pages.append(pg)
        items = [{"display_name": f"Paper {pg}-{i}", "abstract_inverted_index": inv(f"battery study {pg} {i}"), "doi": f"https://doi.org/10.1/{pg}{i}",
                  "authorships": [], "id": f"W{pg}{i}", "publication_year": 2021} for i in range(2)] if pg <= 2 else []
        return httpx.Response(200, json={"results": items})

    ok = OpenAlexConnector(Settings(offline=False), client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    ok.min_interval = 0
    bad = OpenAlexConnector(Settings(offline=False), client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))), sleep=lambda s: None)
    bad.min_interval = 0
    out = store.sync_topic(sf, {"openalex": ok, "arxiv": bad}, "battery", "technology", ["openalex", "arxiv", "nope"], limit=10, per_page=2)
    assert pages == [1, 2, 3] and out[0] == {"source": "openalex", "status": "ok", "fetched": 4, "new": 4, "error": None}
    assert out[1]["status"] == "failed" and out[2]["status"] == "failed"
    s = sf()
    assert {r.source: r.status for r in s.scalars(select(SyncRun))} == {"openalex": "ok", "arxiv": "failed", "nope": "failed"}
    assert store.stats(s)["total"] == 4
    assert store.sync_topic(sf, {"openalex": ok}, "battery", "technology", ["openalex"], limit=10, per_page=2)[0]["new"] == 0  # re-sync is idempotent


def test_index_ranks_relevant_first_filters_domain_and_excludes_retracted(env):
    _, sf, _ = env
    s = sf()
    store.upsert(s, [P("Perovskite solar cell humidity degradation", "Moisture ingress degrades perovskite solar cells.", "10.1/p"),
                     P("Convolutional networks for image classification", "We train deep networks on image datasets.", "10.1/c"),
                     P("Retracted perovskite humidity claim", "Moisture ingress degrades perovskite solar cells.", "10.1/r", retracted=True)], "technology", "x")
    store.upsert(s, [P("Orbital debris tracking", "Satellite orbit propagation of debris.", "10.1/o")], "space", "y")
    s.commit()
    idx = CorpusIndex(s)
    hits = idx.search("humidity degradation of perovskite solar cells")
    assert [h[0].doi for h in hits] == ["10.1/p"] and hits[0][1] > 0.3
    assert idx.search("satellite orbit", domain="technology") == [] and idx.search("satellite orbit", domain="space")[0][0].doi == "10.1/o"
    assert idx.search("") == []


def test_pipeline_uses_local_corpus_offline_and_api_exposes_it(env):
    settings, sf, store_ = env
    settings.offline = True
    s = sf()
    store.upsert(s, [P("Graphene coating extends battery lifespan", "We found that graphene coating increases battery lifespan in a randomized benchmark.", "10.1/g",
                       pub_types=["article"]),
                     P("Battery lifespan and energy retention", "Battery lifespan improves energy retention in cells.", "10.1/h")], "technology", "seed")
    s.commit()
    c = authenticated_client(create_app(settings, sf, store_, connectors={}))
    pid, _, job = _run(c, make_pdf())
    assert job["status"] == "completed", job
    acq = job["result"]["tasks"]["acquire_technology"]
    assert acq["output"]["n_local"] >= 1 and acq["status"] == "completed"
    b = next(b for b in c.get(f"/api/v1/projects/{pid}/beliefs").json() if "graphene coating increases" in b["claim_text"])
    assert b["support_class"] != "not_independently_verifiable" and b["n_effective"] >= 1
    assert c.get("/api/v1/corpus/stats").json()["total"] == 2
    assert c.get("/api/v1/corpus/search", params={"q": "graphene battery lifespan"}).json()[0]["doi"] == "10.1/g"
    assert c.post("/api/v1/corpus/sync", json={"topics": ["x"], "domain": "bogus"}).status_code == 422
