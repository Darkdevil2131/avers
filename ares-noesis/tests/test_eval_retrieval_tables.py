import json

import pymupdf
import pytest

from noesis.corpus import store
from noesis.corpus.index import CorpusIndex
from noesis.engines import stats_engine
from noesis.eval import benchmarks as B
from noesis.eval.metrics import classification_report, prf
from noesis.ingestion.claims import extract_claims
from noesis.ingestion.parse import parse_document
from tests.test_corpus import P


def test_prf_and_classification_report_math():
    assert prf(8, 2, 2) == {"precision": 0.8, "recall": 0.8, "f1": 0.8, "tp": 8, "fp": 2, "fn": 2}
    assert prf(0, 0, 0)["f1"] == 0.0
    gold = ["A", "A", "B", "B", "C", "C"]
    pred = ["A", "B", "B", "B", "C", "A"]
    r = classification_report(gold, pred, ["A", "B", "C"], n_boot=200)
    assert r["accuracy"] == pytest.approx(4 / 6, abs=1e-4) and r["per_class"]["B"]["recall"] == 1.0 and r["per_class"]["B"]["precision"] == pytest.approx(2 / 3, abs=1e-3)
    assert r["confusion"]["A"] == {"A": 1, "B": 1, "C": 0} and r["macro_f1_ci95"][0] <= r["macro_f1"] <= r["macro_f1_ci95"][1]


def test_scifact_loader_semantics_and_stance_eval(tmp_path):
    corpus = tmp_path / "corpus.jsonl"; claims = tmp_path / "claims.jsonl"
    corpus.write_text("\n".join(json.dumps(d) for d in [
        {"doc_id": 1, "title": "Graphene", "abstract": ["We found that graphene coating increases battery lifespan."]},
        {"doc_id": 2, "title": "Hurts", "abstract": ["We found that graphene coating decreases battery lifespan."]},
        {"doc_id": 3, "title": "Unrelated", "abstract": ["Cats sleep a lot."]}]))
    claims.write_text("\n".join(json.dumps(d) for d in [
        {"id": 10, "claim": "Graphene coating increases battery lifespan.", "evidence": {"1": [{"sentences": [0], "label": "SUPPORT"}], "2": [{"sentences": [0], "label": "CONTRADICT"}]}, "cited_doc_ids": [1, 2]},
        {"id": 11, "claim": "Graphene coating increases battery lifespan.", "evidence": {}, "cited_doc_ids": [3]},
        {"id": 12, "claim": "x", "evidence": {"1": [{"label": "SUPPORT"}, {"label": "CONTRADICT"}]}, "cited_doc_ids": [1]},      # ambiguous -> excluded
        {"id": 13, "claim": "x", "evidence": {}, "cited_doc_ids": [99]}]))                                                      # missing doc -> skipped
    pairs = B.load_scifact(str(claims), str(corpus))
    assert [(p["claim_id"], p["doc_id"], p["gold"]) for p in pairs] == [(10, "1", "SUPPORT"), (10, "2", "CONTRADICT"), (11, "3", "NEI")]
    rep = B.eval_stance(pairs, B.predict_lexical, "lexical_v1")
    assert rep["accuracy"] == 1.0 and rep["n"] == 3 and rep["system"] == "lexical_v1"
    bad = B.eval_stance(pairs, lambda c, t, a: "SUPPORT", "always_support")
    assert bad["accuracy"] == pytest.approx(1 / 3, abs=1e-3) and bad["per_class"]["CONTRADICT"]["recall"] == 0.0


def test_triple_eval(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in [
        {"sentence": "Dose increases yield.", "triple": {"subject": "dose", "relation": "increases", "object": "yield"}},
        {"sentence": "Dose decreases yield.", "triple": {"subject": "dose", "relation": "increases", "object": "yield"}},     # wrong relation
        {"sentence": "Nothing to see here.", "triple": None}]))
    r = B.eval_triples(str(f))
    assert (r["tp"], r["fp"], r["fn"]) == (1, 1, 1)


def test_lsa_retrieves_synonyms_that_tfidf_alone_misses(env):
    _, sf, _ = env
    s = sf()
    papers = [P(f"Automobile engine study {i}", f"The car automobile engine and wheel and road noise {i} vibration chassis.", f"10.9/c{i}") for i in range(12)]
    papers += [P(f"Protein folding {i}", f"Protein cell gene expression pathway receptor binding kinase {i} enzyme.", f"10.9/p{i}") for i in range(12)]
    papers.append(P("Engine design note", "A note on the car engine and wheel and road chassis vibration only.", "10.9/target"))
    store.upsert(s, papers, "technology", "t")
    s.commit()
    hits = CorpusIndex(s).search("automobile", k=30)
    dois = [h[0].doi for h in hits]
    assert "10.9/target" in dois                                      # shares no query word, found via latent semantics
    assert not any(d.startswith("10.9/p") for d in dois)              # unrelated topic excluded


def make_table_pdf():
    doc = pymupdf.open(); pg = doc.new_page()
    pg.insert_textbox(pymupdf.Rect(40, 40, 560, 120), "Results\nWe measured group means.", fontsize=10)
    rows = [["Group", "Mean", "n"], ["A", "5.19", "28"], ["B", "5.18", "28"]]
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            rect = pymupdf.Rect(60 + c * 90, 150 + r * 28, 150 + c * 90, 178 + r * 28)
            pg.draw_rect(rect, color=(0, 0, 0), width=0.8)
            pg.insert_text((rect.x0 + 6, rect.y0 + 18), val, fontsize=10)
    return doc.tobytes()


def test_pdf_tables_extracted_and_grim_checked():
    d = parse_document("t.pdf", make_table_pdf())
    assert d.tables and d.tables[0]["rows"][0] == ["Group", "Mean", "n"]
    cl = [c for c in extract_claims(d) if c["kind"] == "table"]
    assert cl and cl[0]["page"] == 1
    g = stats_engine.grim_table(cl[0]["meta"]["rows"])
    assert g["applicable"] and g["n_impossible"] == 1 and [x["possible"] for x in g["results"]] == [False, True]     # 5.19 impossible for n=28
    assert stats_engine.grim_table([["x", "y"], ["1", "2"]])["applicable"] is False


def test_metrics_endpoint_exposes_counts(client):
    pid = client.post("/api/v1/projects", json={"name": "m"}).json()["id"]
    client.get(f"/api/v1/projects/{pid}/claims")
    txt = client.get("/metrics").text
    assert 'noesis_http_requests_total{method="POST",route="/api/v1/projects",status="201"} 1' in txt
    assert "noesis_corpus_papers 0" in txt and "noesis_beliefs 0" in txt


def test_unlabelled_rows_are_skipped_and_label_sheet_round_trips(tmp_path):
    import json
    from noesis.eval.benchmarks import eval_triples, export_label_sheet
    f = tmp_path / "sheet.jsonl"
    n = export_label_sheet([("10.1/a", "Graphene coating increases battery lifespan."), ("10.1/b", "We found that heat decreases yield.")], str(f), n=5)
    assert n == 2
    rows = [json.loads(x) for x in f.read_text().splitlines()]
    assert all(r["labelled"] is False and r["triple"] is None for r in rows)
    rows[0].update({"labelled": True, "triple": {"subject": "graphene coating", "relation": "increases", "object": "battery lifespan"}})
    f.write_text("\n".join(json.dumps(r) for r in rows))
    out = eval_triples(str(f))
    assert out["skipped_unlabelled"] == 1                   # the untouched row is not scored as a "no triple" negative
    assert out["tp"] + out["fp"] + out["fn"] >= 1
