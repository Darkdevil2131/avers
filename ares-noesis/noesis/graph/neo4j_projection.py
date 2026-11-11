"""Neo4j projection of the knowledge base.

Postgres/SQLite stays the source of truth; this graph is a rebuildable projection. Every statement is an idempotent MERGE keyed on a stable
id, so projecting twice gives the same graph. `statements()` produces the Cypher and parameters without needing a database; `project()` runs them
through the official `neo4j` driver (optional dependency) in batches inside one transaction per batch.

Graph model: (Belief)-[:EVIDENCED_BY {stance, grade, design, group}]->(Paper); (Paper)-[:SHARES_LINEAGE]-(Paper) for papers in one independence group."""
from itertools import combinations

from sqlalchemy import select

from ..models import Belief, EvidenceItem, ExternalPaper

CONSTRAINTS = [
    "CREATE CONSTRAINT belief_id IF NOT EXISTS FOR (b:Belief) REQUIRE b.id IS UNIQUE",
    "CREATE CONSTRAINT paper_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.id IS UNIQUE",
]


def statements(s, project_id: int) -> list:
    out = [(c, {}) for c in CONSTRAINTS]
    beliefs = list(s.scalars(select(Belief).where(Belief.project_id == project_id)))
    for b in beliefs:
        out.append(("MERGE (b:Belief {id: $id}) SET b.claim = $claim, b.assessment = $assessment, b.support_class = $sc, "
                    "b.posterior = $posterior, b.n_effective = $n, b.version = $version, b.project = $project",
                    {"id": f"belief:{b.id}", "claim": b.claim_text, "assessment": b.assessment, "sc": b.support_class,
                     "posterior": b.posterior, "n": b.n_effective, "version": b.version, "project": project_id}))
        groups = {}
        for e in s.scalars(select(EvidenceItem).where(EvidenceItem.belief_id == b.id, EvidenceItem.active.is_(True))):
            key = f"paper:{e.paper_id}" if e.paper_id else f"doi:{e.doi or e.title}"
            out.append(("MERGE (p:Paper {id: $pid}) SET p.title = $title, p.doi = $doi, p.source = $source, p.retracted = $retracted "
                        "WITH p MATCH (b:Belief {id: $bid}) "
                        "MERGE (b)-[r:EVIDENCED_BY]->(p) SET r.stance = $stance, r.grade = $grade, r.design = $design, r.group = $group",
                        {"pid": key, "title": e.title, "doi": e.doi, "source": e.source, "retracted": e.retracted, "bid": f"belief:{b.id}",
                         "stance": e.stance, "grade": e.grade_label, "design": e.design, "group": e.independence_group}))
            groups.setdefault(e.independence_group, []).append(key)
        for members in groups.values():
            for a, c in combinations(sorted(set(members)), 2):
                out.append(("MATCH (a:Paper {id: $a}), (c:Paper {id: $c}) MERGE (a)-[:SHARES_LINEAGE]->(c)", {"a": a, "c": c}))
    return out


def project(s, project_id: int, driver, batch: int = 200) -> dict:
    """Run the statements through a neo4j driver (anything with .session().run / .execute_write). Returns counts."""
    stmts = statements(s, project_id)
    with driver.session() as sess:
        for i in range(0, len(stmts), batch):
            chunk = stmts[i:i + batch]

            def work(tx, chunk=chunk):
                for q, params in chunk:
                    tx.run(q, params)
            sess.execute_write(work)
    return {"statements": len(stmts)}
