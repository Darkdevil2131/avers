"""Evidence graph built from the relational store (Postgres is the source of truth; Neo4j is a later projection)."""
import math

import networkx as nx
from sqlalchemy import select

from ..ingestion.claims import triples_contradict
from ..models import Belief, Claim, Document, EvidenceItem, ExternalPaper


def _sign(t: dict) -> int:
    return (1 if t["relation"] == "increases" else -1)


def _add_triple(G, t: dict, src: str, domains: list):
    if t.get("negated"):
        return
    for name in (t["subject"], t["object"]):
        n = f"entity:{name}"
        if n not in G:
            G.add_node(n, type="entity", label=name, domains=[])
        G.nodes[n]["domains"] = sorted(set(G.nodes[n]["domains"]) | set(domains))
    G.add_edge(f"entity:{t['subject']}", f"entity:{t['object']}", key=src, relation=t["relation"], sign=_sign(t),
               source=src, kind="entity_relation", negated=t.get("negated", False), domains=list(domains))


def build_graph(s, project_id: int) -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()
    for d in s.scalars(select(Document).where(Document.project_id == project_id)):
        doms = (d.meta or {}).get("routing", {}).get("domains", [])
        G.add_node(f"doc:{d.id}", type="document", label=d.filename, domains=doms)
        for c in s.scalars(select(Claim).where(Claim.document_id == d.id)):
            G.add_node(f"claim:{c.id}", type="claim", label=c.text[:120], page=c.page, section=c.section, kind=c.kind)
            G.add_edge(f"doc:{d.id}", f"claim:{c.id}", key="contains", kind="CONTAINS_CLAIM")
            tr = (c.meta or {}).get("triple")
            if tr:
                _add_triple(G, tr, f"claim:{c.id}", doms)
    for p in s.scalars(select(ExternalPaper).where(ExternalPaper.project_id == project_id)):
        G.add_node(f"paper:{p.id}", type="paper", label=p.title[:120], doi=p.doi, source=p.source, license=p.license)
        for tr in (p.meta or {}).get("triples", []):
            _add_triple(G, tr, f"paper:{p.id}", [(p.meta or {}).get("domain", "")])
    for b in s.scalars(select(Belief).where(Belief.project_id == project_id, Belief.status != "superseded")):
        G.add_node(f"belief:{b.id}", type="belief", label=b.claim_text[:120], assessment=b.assessment, status=b.status)
        if b.claim_id:
            G.add_edge(f"belief:{b.id}", f"claim:{b.claim_id}", key="about", kind="ABOUT")
        for e in s.scalars(select(EvidenceItem).where(EvidenceItem.belief_id == b.id, EvidenceItem.active.is_(True))):
            G.add_node(f"evidence:{e.id}", type="evidence", label=e.title[:120], grade=e.grade, design=e.design)
            kind = {"supports": "SUPPORTED_BY", "contradicts": "CONTRADICTED_BY"}.get(e.stance, "RELATED_TO")
            G.add_edge(f"belief:{b.id}", f"evidence:{e.id}", key=f"ev{e.id}", kind=kind, grade=e.grade, group=e.independence_group)
            if e.paper_id:
                G.add_edge(f"evidence:{e.id}", f"paper:{e.paper_id}", key="from", kind="FROM_PAPER")
    return G


def entity_digraph(G) -> nx.DiGraph:
    E = nx.DiGraph()
    for u, v, k, d in G.edges(keys=True, data=True):
        if d.get("kind") == "entity_relation":
            if E.has_edge(u, v):
                E[u][v]["sources"].append(d["source"])
                E[u][v]["signs"].append(d["sign"])
            else:
                E.add_edge(u, v, sources=[d["source"]], signs=[d["sign"]])
    for n, d in G.nodes(data=True):
        if d.get("type") == "entity" and n in E:
            E.nodes[n].update(d)
    return E


def find_gaps(E, limit: int = 15) -> list:
    """Open directed chains a->b->c with no a-c link. Score = sum 1/log(deg(b)+1) (Adamic-Adar style)."""
    best = {}
    for b in E.nodes:
        for a in E.predecessors(b):
            for c in E.successors(b):
                if a == c or E.has_edge(a, c) or E.has_edge(c, a):
                    continue
                sa = 1 if sum(E[a][b]["signs"]) >= 0 else -1
                sc = 1 if sum(E[b][c]["signs"]) >= 0 else -1
                score = 1 / math.log(E.degree(b) + 1.5)
                key = (a, c)
                rec = best.setdefault(key, {"a": a, "c": c, "mediators": [], "score": 0.0, "sign": sa * sc, "sources": set()})
                rec["mediators"].append(b)
                rec["score"] += score
                rec["sources"] |= set(E[a][b]["sources"]) | set(E[b][c]["sources"])
    out = sorted(best.values(), key=lambda r: -r["score"])[:limit]
    for r in out:
        r["sources"] = sorted(r["sources"])
    return out


def find_contradictions(E) -> list:
    out = []
    for u, v, d in E.edges(data=True):
        if len(set(d["signs"])) > 1:
            out.append({"subject": u, "object": v, "sources": d["sources"], "signs": d["signs"]})
    return out


def cross_domain_entities(E) -> list:
    return [{"entity": n, "domains": d["domains"]} for n, d in E.nodes(data=True) if len(set(d.get("domains", [])) - {""}) >= 2]


def to_json(G) -> dict:
    return nx.node_link_data(G, edges="edges")
