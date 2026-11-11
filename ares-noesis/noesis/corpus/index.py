"""Local retrieval over the corpus: TF-IDF (unigram+bigram, sublinear tf) + cosine. CPU only, no network.
Scale path: swap `_vectors` for dense embeddings + pgvector/FAISS behind the same search() contract."""
import numpy as np
from sqlalchemy import func, select

from ..models import CorpusPaper

_CACHE: dict = {}


def _load_embedder():
    """Optional dense embeddings: NOESIS_EMBEDDER=st:all-MiniLM-L6-v2 (requires `pip install sentence-transformers`)."""
    from ..config import get_settings
    spec = get_settings().embedder
    if get_settings().offline or not spec.startswith("st:"):
        return None
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    model = SentenceTransformer(spec[3:])
    return lambda texts: np.asarray(model.encode(list(texts), normalize_embeddings=True))


class CorpusIndex:
    def __init__(self, s):
        self.s = s

    def _state(self):
        n, mx = self.s.execute(select(func.count(CorpusPaper.id), func.max(CorpusPaper.id))).one()
        retracted_ids = tuple(self.s.scalars(
            select(CorpusPaper.id).where(CorpusPaper.retracted.is_(True)).order_by(CorpusPaper.id)
        ))
        key = (self.s.get_bind(), n, mx, retracted_ids)
        if key in _CACHE:
            return _CACHE[key]
        from sklearn.feature_extraction.text import TfidfVectorizer
        from ..config import get_settings
        cfg = get_settings()
        rows = list(self.s.execute(select(CorpusPaper.id, CorpusPaper.title, CorpusPaper.abstract, CorpusPaper.domain)
                                   .where(CorpusPaper.retracted.is_not(True)).order_by(CorpusPaper.id.desc()).limit(cfg.index_max_docs)))
        if not rows:
            return None
        # one-off bigrams dominate the vocabulary (memory/time) and carry no retrieval signal: drop terms seen in <2 docs once the corpus is non-trivial
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True, dtype=np.float32,
                              min_df=2 if len(rows) >= 200 else 1, max_features=cfg.index_max_features)
        texts = [f"{r.title}. {r.title}. {r.abstract}" for r in rows]
        mat = vec.fit_transform(texts)
        svd = lsa = dense = None
        if len(rows) >= 20 and mat.shape[1] > 10:      # latent semantic analysis: lets synonyms/related terms match
            from sklearn.decomposition import TruncatedSVD
            from sklearn.preprocessing import normalize
            # untuned heuristic: ~1 latent component per 12 docs (capped at 100); tune with `noesis eval`
            svd = TruncatedSVD(n_components=min(100, max(2, len(rows) // 12), mat.shape[1] - 1), random_state=0)
            lsa = normalize(svd.fit_transform(mat))
        emb = _load_embedder()
        if emb is not None:
            dense = emb(texts)
        _CACHE.clear()
        _CACHE[key] = (vec, mat, [r.id for r in rows], [r.domain for r in rows], svd, lsa, emb, dense)
        return _CACHE[key]

    def search(self, query: str, k: int = 5, domain: str | None = None, min_score: float = 0.12) -> list:
        st = self._state()
        if st is None or not query.strip():
            return []
        vec, mat, ids, doms, svd, lsa, emb, dense = st
        q = vec.transform([query])
        scores = (mat @ q.T).toarray().ravel()
        if svd is not None:
            from sklearn.preprocessing import normalize
            lsa_s = lsa @ normalize(svd.transform(q)).ravel()
            scores = 0.6 * scores + 0.4 * np.clip(lsa_s, 0, None)     # heuristic blend, not tuned: tune on an eval set
        if dense is not None:
            scores = 0.5 * scores + 0.5 * np.clip(dense @ emb([query])[0], 0, None)
        order = scores.argsort()[::-1]
        from ..config import get_settings
        pool_size = k * 4 if get_settings().rerank else k
        cand = []
        for i in order:
            if scores[i] < min_score or len(cand) >= pool_size:
                break
            if domain and doms[i] and doms[i] != domain:
                continue
            paper = self.s.get(CorpusPaper, ids[i])
            if paper is not None and paper.retracted is not True:
                cand.append((paper, float(scores[i])))
        if get_settings().rerank and len(cand) > 1:
            from .rerank import rerank_order
            cand = [cand[j] for j in rerank_order(query, [f"{p.title}. {p.abstract}" for p, _ in cand])]
        return cand[:k]
