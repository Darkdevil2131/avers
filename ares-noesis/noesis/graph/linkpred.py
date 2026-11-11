"""TransE knowledge-graph embedding (numpy) for link prediction: score(h, r, t) = -||h + r - t||.
Trains on the entity-relation triples in the evidence graph. Refuses to train on tiny graphs (embeddings would be noise)."""
import numpy as np

MIN_TRIPLES = 15


class TransE:
    def __init__(self, dim=16, margin=1.0, lr=0.05, epochs=300, seed=0):
        self.dim, self.margin, self.lr, self.epochs, self.seed = dim, margin, lr, epochs, seed
        self.ents: dict = {}
        self.rels: dict = {}

    def fit(self, triples: list):
        if len(triples) < MIN_TRIPLES:
            raise ValueError(f"need >= {MIN_TRIPLES} triples to train (got {len(triples)})")
        rng = np.random.default_rng(self.seed)
        for h, r, t in triples:
            self.ents.setdefault(h, len(self.ents)); self.ents.setdefault(t, len(self.ents)); self.rels.setdefault(r, len(self.rels))
        E = rng.uniform(-6 / np.sqrt(self.dim), 6 / np.sqrt(self.dim), (len(self.ents), self.dim))
        R = rng.uniform(-6 / np.sqrt(self.dim), 6 / np.sqrt(self.dim), (len(self.rels), self.dim))
        R /= np.linalg.norm(R, axis=1, keepdims=True)
        T = np.array([(self.ents[h], self.rels[r], self.ents[t]) for h, r, t in triples])
        known = set(map(tuple, T))
        n = len(self.ents)
        for _ in range(self.epochs):
            E /= np.maximum(np.linalg.norm(E, axis=1, keepdims=True), 1.0)
            for i in rng.permutation(len(T)):
                h, r, t = T[i]
                for _try in range(10):
                    t2 = int(rng.integers(n))
                    if (h, r, t2) not in known:
                        break
                d_pos = E[h] + R[r] - E[t]
                d_neg = E[h] + R[r] - E[t2]
                if self.margin + np.linalg.norm(d_pos) - np.linalg.norm(d_neg) > 0:
                    g_pos = d_pos / (np.linalg.norm(d_pos) + 1e-9)
                    g_neg = d_neg / (np.linalg.norm(d_neg) + 1e-9)
                    E[h] -= self.lr * (g_pos - g_neg); R[r] -= self.lr * (g_pos - g_neg)
                    E[t] += self.lr * g_pos; E[t2] -= self.lr * g_neg
        self.E, self.R = E, R
        return self

    def score(self, h, r, t) -> float:
        return -float(np.linalg.norm(self.E[self.ents[h]] + self.R[self.rels[r]] - self.E[self.ents[t]]))

    def rank_tail(self, h, r, t) -> int:
        """1 = best. Rank of t among all entities as the tail of (h, r, ?)."""
        q = self.E[self.ents[h]] + self.R[self.rels[r]]
        d = np.linalg.norm(self.E - q, axis=1)
        return int((d < d[self.ents[t]]).sum()) + 1


def entity_triples(E) -> list:
    """Entity digraph -> (head, relation, tail) triples using the majority sign of each edge."""
    out = []
    for u, v, d in E.edges(data=True):
        out.append((u, "increases" if sum(d["signs"]) >= 0 else "decreases", v))
    return out


def rank_candidates(E, candidates: list) -> dict:
    """candidates: [(a, sign, c)] -> {(a, c): rank} or {} if the graph is too small to train on."""
    triples = entity_triples(E)
    if len(triples) < MIN_TRIPLES:
        return {}
    m = TransE().fit(triples)
    out = {}
    for a, sign, c in candidates:
        if a in m.ents and c in m.ents:
            out[(a, c)] = m.rank_tail(a, "increases" if sign > 0 else "decreases", c)
    return out
