"""Command line: sync real literature into the database, inspect it, search it, serve the API.
  python -m noesis.cli sync --topic "perovskite solar cell degradation" --domain technology --limit 200
  python -m noesis.cli stats | search "graphene battery" | serve"""
import argparse
import json

from .config import get_settings
from .connectors.sources import default_connectors
from .corpus import store
from .corpus.index import CorpusIndex
from .db import make_engine, make_session_factory


def main(argv=None):
    ap = argparse.ArgumentParser(prog="noesis")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sy = sub.add_parser("sync")
    sy.add_argument("--topic", required=True, action="append")
    sy.add_argument("--domain", required=True, help="medicine|technology|space|chemistry|physics|earth_science|life_science|social_science|mathematics|general")
    sy.add_argument("--sources", default="openalex,arxiv,crossref,europepmc")
    sy.add_argument("--limit", type=int, default=100)
    sub.add_parser("stats")
    se = sub.add_parser("search"); se.add_argument("query"); se.add_argument("-k", type=int, default=5)
    sub.add_parser("refresh", help="re-run every previously synced topic to pull newly published papers (cron-able)")
    ev = sub.add_parser("eval", help="measure extraction/stance quality on labelled data")
    ev.add_argument("what", choices=["scifact", "triples"])
    ev.add_argument("--claims"); ev.add_argument("--corpus"); ev.add_argument("--file"); ev.add_argument("--llm", action="store_true"); ev.add_argument("--limit", type=int)
    ls = sub.add_parser("labelsheet", help="export sampled corpus sentences to a JSONL sheet for hand-labelling (gold set for `eval triples`)")
    ls.add_argument("--out", required=True); ls.add_argument("-n", type=int, default=200)
    on = sub.add_parser("ontology", help="load an OBO ontology file (e.g. a Gene Ontology or ChEBI release you downloaded)")
    on.add_argument("--file", required=True); on.add_argument("--name", required=True)
    pg = sub.add_parser("project-graph", help="project a project's beliefs and evidence into Neo4j (needs `pip install neo4j` and NOESIS_NEO4J_URL)")
    pg.add_argument("--project", type=int, required=True); pg.add_argument("--dry-run", action="store_true", help="print the Cypher instead of running it")
    sub.add_parser("worker", help="process queued jobs (use with NOESIS_QUEUE_MODE=db); run several for parallelism")
    sub.add_parser("serve")
    a = ap.parse_args(argv)
    st = get_settings()
    sf = make_session_factory(make_engine(st.database_url))
    if a.cmd == "sync":
        conns = default_connectors(st)
        for topic in a.topic:
            for r in store.sync_topic(sf, conns, topic, a.domain, a.sources.split(","), a.limit):
                print(json.dumps({"topic": topic, **r}))
    elif a.cmd == "refresh":
        from sqlalchemy import select
        from .models import SyncRun
        s = sf()
        seen = {(r.query, r.domain) for r in s.scalars(select(SyncRun)) if r.domain}
        conns = default_connectors(st)
        for topic, dom in sorted(seen):
            for r in store.sync_topic(sf, conns, topic, dom, ["openalex", "arxiv", "crossref", "europepmc"], 100):
                print(json.dumps({"topic": topic, **r}))
    elif a.cmd == "stats":
        s = sf(); print(json.dumps(store.stats(s), indent=2))
    elif a.cmd == "search":
        s = sf()
        for p, sc in CorpusIndex(s).search(a.query, a.k):
            print(f"{sc:.2f}  [{p.source}] {p.title[:90]}  ({p.year}, {p.design}, license={p.license or 'unknown'})")
    elif a.cmd == "eval":
        from .eval import benchmarks as B
        if a.what == "scifact":
            pairs = B.load_scifact(a.claims, a.corpus)
            print(json.dumps(B.eval_stance(pairs, B.predict_lexical, "lexical_v1", a.limit), indent=2))
            if a.llm:
                from .llm.client import LLMClient
                llm = LLMClient(st); llm.settings.llm_max_calls = 10 ** 9
                print(json.dumps(B.eval_stance(pairs, B.make_llm_predictor(llm), "llm_nli_v1", a.limit), indent=2))
        else:
            print(json.dumps(B.eval_triples(a.file), indent=2))
    elif a.cmd == "labelsheet":
        from sqlalchemy import select
        from .eval.benchmarks import export_label_sheet
        from .ingestion.claims import FINDING_CUE
        from .ingestion.parse import split_sentences
        from .models import CorpusPaper
        s = sf()
        src = [(p.doi, x) for p in s.scalars(select(CorpusPaper).where(CorpusPaper.retracted.is_not(True))) for x in split_sentences(p.abstract or "") if FINDING_CUE.search(x)]
        print(json.dumps({"written": export_label_sheet(src, a.out, a.n), "candidates": len(src), "out": a.out}))
    elif a.cmd == "ontology":
        from .ontology.obo import load_obo
        s = sf(); print(json.dumps(load_obo(s, open(a.file, encoding="utf-8").read(), a.name))); s.commit()
    elif a.cmd == "project-graph":
        from .graph.neo4j_projection import project, statements
        s = sf()
        if a.dry_run:
            for q, prm in statements(s, a.project):
                print(q, json.dumps(prm, default=str))
        else:
            raise SystemExit("Neo4j network projection is disabled")
    elif a.cmd == "worker":
        import os
        from . import worker
        from .llm.client import LLMClient
        from .storage import get_store
        worker.run_forever(sf, get_store(st), st, f"worker-{os.getpid()}")
    elif a.cmd == "serve":
        import uvicorn
        uvicorn.run("noesis.api.main:app_factory", factory=True, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
