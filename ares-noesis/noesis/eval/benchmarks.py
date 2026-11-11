"""Benchmarks named in the plan. SciFact (claim verification) loader + stance evaluation; triple-extraction evaluation.
Data is NOT bundled: download SciFact (claims_dev.jsonl, corpus.jsonl) yourself and pass the paths."""
import json

from ..ingestion.claims import extract_triple
from ..ingestion.parse import split_sentences
from ..llm import extract as llmx
from ..verification.evidence import lexical_stance
from .metrics import classification_report, prf

LABELS = ["SUPPORT", "CONTRADICT", "NEI"]


def load_scifact(claims_path: str, corpus_path: str) -> list:
    """SciFact format. Gold per (claim, cited doc): SUPPORT/CONTRADICT from the evidence annotation, else NEI."""
    corpus = {}
    for line in open(corpus_path, encoding="utf-8"):
        d = json.loads(line)
        corpus[str(d["doc_id"])] = (d.get("title", ""), " ".join(d.get("abstract", [])))
    pairs = []
    for line in open(claims_path, encoding="utf-8"):
        c = json.loads(line)
        ev = {str(k): v for k, v in (c.get("evidence") or {}).items()}
        for did in [str(x) for x in c.get("cited_doc_ids", list(ev))]:
            if did not in corpus:
                continue
            labs = {e["label"] for e in ev.get(did, [])}
            gold = "SUPPORT" if labs == {"SUPPORT"} else "CONTRADICT" if labs == {"CONTRADICT"} else "NEI"
            if len(labs) > 1:
                continue  # mixed annotations on one doc: ambiguous, excluded
            pairs.append({"claim_id": c["id"], "claim": c["claim"], "doc_id": did, "title": corpus[did][0], "abstract": corpus[did][1], "gold": gold})
    return pairs


def predict_lexical(claim: str, title: str, abstract: str) -> str:
    triples = [t for s in split_sentences(abstract) if (t := extract_triple(s))]
    r = lexical_stance(claim, extract_triple(claim), f"{title}. {abstract}", triples)
    return {"supports": "SUPPORT", "contradicts": "CONTRADICT"}.get(r["stance"], "NEI")


def make_llm_predictor(llm):
    def f(claim, title, abstract):
        r, err = llmx.safe(llmx.judge_stance, llm, claim, f"{title}. {abstract}")
        return {"supports": "SUPPORT", "contradicts": "CONTRADICT"}.get((r or {}).get("stance"), "NEI")
    return f


def eval_stance(pairs: list, predictor, name: str, limit: int | None = None) -> dict:
    pairs = pairs[:limit] if limit else pairs
    pred = [predictor(p["claim"], p["title"], p["abstract"]) for p in pairs]
    rep = classification_report([p["gold"] for p in pairs], pred, LABELS)
    return {"benchmark": "scifact_stance (claim, cited abstract) -> SUPPORT/CONTRADICT/NEI", "system": name, **rep}


def eval_triples(path: str) -> dict:
    """JSONL rows: {"sentence": str, "triple": {"subject","relation","object"} | null}. Exact match on normalized fields."""
    tp = fp = fn = 0
    skipped = 0
    for line in open(path, encoding="utf-8"):
        row = json.loads(line)
        if row.get("labelled") is False:        # exported but not yet hand-labelled: counting it would score every blank as "no triple"
            skipped += 1
            continue
        got, gold = extract_triple(row["sentence"]), row.get("triple")
        key = lambda t: (t["subject"].lower().strip(), t["relation"], t["object"].lower().strip()) if t else None
        if got and gold and key(got) == key(gold):
            tp += 1
        else:
            fp += 1 if got else 0
            fn += 1 if gold else 0
    return {"benchmark": "triple_extraction_exact_match", "system": "rules_v1", "skipped_unlabelled": skipped, **prf(tp, fp, fn)}


def export_label_sheet(sentences_source, path: str, n: int = 200, seed: int = 0) -> int:
    """Write a hand-labelling sheet. sentences_source: iterable of (doi, sentence). Rows start `labelled: false`;
    fill `triple` ({"subject","relation","object"} or null when the sentence states no such claim) and set `labelled: true`."""
    import random
    rows = list(sentences_source)
    random.Random(seed).shuffle(rows)
    with open(path, "w", encoding="utf-8") as f:
        for i, (doi, sent) in enumerate(rows[:n]):
            f.write(json.dumps({"id": i, "doi": doi, "sentence": sent, "triple": None, "labelled": False}) + "\n")
    return min(n, len(rows))
