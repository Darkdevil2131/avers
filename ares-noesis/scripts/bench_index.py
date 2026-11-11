"""Benchmark corpus ingest + index build + query latency on SYNTHETIC text (Zipf-distributed vocabulary).
Numbers show scaling behaviour of the in-process index; they are not representative of real abstract quality."""
import random, resource, sys, time
sys.path.insert(0, ".")
import numpy as np
from noesis.connectors.base import Paper
from noesis.corpus import store
from noesis.corpus.index import CorpusIndex, _CACHE
from noesis.db import make_engine, make_session_factory

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
rng = np.random.default_rng(0)
vocab = [f"w{i}" for i in range(8000)]
p = 1 / np.arange(1, len(vocab) + 1); p /= p.sum()
sf = make_session_factory(make_engine("sqlite://"))
s = sf()
t0 = time.perf_counter()
papers = [Paper(source="bench", title=" ".join(rng.choice(vocab, 8, p=p)), abstract=" ".join(rng.choice(vocab, 150, p=p)), doi=f"10.0/{i}", authors=["A B"]) for i in range(N)]
t_gen = time.perf_counter() - t0
t0 = time.perf_counter(); store.upsert(s, papers, "technology", "bench"); s.commit(); t_ingest = time.perf_counter() - t0
_CACHE.clear()
t0 = time.perf_counter(); CorpusIndex(s).search("w3 w10 w50"); t_build = time.perf_counter() - t0
qs = [" ".join(rng.choice(vocab, 3, p=p)) for _ in range(50)]
lat = []
for q in qs:
    t0 = time.perf_counter(); CorpusIndex(s).search(q, 8); lat.append((time.perf_counter() - t0) * 1000)
print(f"N={N:>6} ingest={t_ingest:6.1f}s ({N/t_ingest:5.0f} papers/s)  first-query(index build)={t_build:6.1f}s  query p50={np.percentile(lat,50):6.1f}ms p95={np.percentile(lat,95):6.1f}ms  peak_rss={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:6.0f}MB")
