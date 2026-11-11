"""Lexical reranker: BM25 over the candidate set, fused with the first-stage order by reciprocal rank fusion (RRF).
No model download. It corrects first-stage (TF-IDF/LSA) mistakes on exact-term matches; it does not understand meaning."""
import math
import re
from collections import Counter

_TOK = re.compile(r"[a-z0-9][a-z0-9\-]+")


def _tokens(text: str) -> list:
    return _TOK.findall((text or "").lower())


def bm25_scores(query: str, docs: list, k1: float = 1.5, b: float = 0.75) -> list:
    toks = [_tokens(d) for d in docs]
    n = len(toks)
    if not n:
        return []
    avg = sum(len(t) for t in toks) / n or 1.0
    df = Counter(w for t in toks for w in set(t))
    q = list(dict.fromkeys(_tokens(query)))
    out = []
    for t in toks:
        tf, score = Counter(t), 0.0
        for w in q:
            if tf[w]:
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                score += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(t) / avg))
        out.append(score)
    return out


def rerank_order(query: str, docs: list, rrf_k: int = 60, bm25_weight: float = 2.0) -> list:
    """Return indexes of docs in fused order (first-stage order = input order). BM25 is weighted above the first stage on purpose:
    with equal weights a one-place disagreement ties and the first-stage leader is never overturned."""
    bm = bm25_scores(query, docs)
    bm_rank = {i: r for r, i in enumerate(sorted(range(len(docs)), key=lambda i: -bm[i]))}
    fused = {i: 1 / (rrf_k + i) + bm25_weight / (rrf_k + bm_rank[i]) for i in range(len(docs))}
    return sorted(range(len(docs)), key=lambda i: -fused[i])
