from noesis.ontology.obo import annotate, load_obo, parse_obo
from tests.test_query import Q, SUPPORT_A, app_with, ask

OBO = """format-version: 1.2
ontology: test

[Term]
id: T:0001
name: graphene coating
def: "A thin carbon layer applied to a surface." [TEST:1]
synonym: "graphene film" EXACT []
synonym: "carbon sheet layer" RELATED []
is_a: T:0000 ! material layer

[Term]
id: T:0002
name: battery lifespan
synonym: "cycle life" EXACT []

[Term]
id: T:0003
name: obsolete thing
is_obsolete: true

[Typedef]
id: part_of
name: part of
"""


def test_parse_obo_reads_terms_synonyms_parents_and_skips_typedefs():
    ts = parse_obo(OBO)
    assert [t["id"] for t in ts] == ["T:0001", "T:0002", "T:0003"]
    t = ts[0]
    assert t["synonyms"] == ["graphene film", "carbon sheet layer"] and t["is_a"] == ["T:0000"] and t["def"].startswith("A thin carbon")
    assert ts[2]["obsolete"] is True


def test_load_is_idempotent_and_annotate_matches_longest_known_terms_only(env):
    _, sf, _ = env
    s = sf()
    assert load_obo(s, OBO, "test") == {"ontology": "test", "new": 3, "updated": 0}
    assert load_obo(s, OBO, "test") == {"ontology": "test", "new": 0, "updated": 3}
    found = annotate(s, "Does a graphene film extend battery cycle life? Also obsolete thing and zorblax.")
    assert [(f["term_id"], f["mention"]) for f in found] == [("T:0001", "graphene film"), ("T:0002", "cycle life")]   # obsolete + unknown never matched
    assert annotate(s, "nothing relevant here") == []
    s.close()


def test_without_an_ontology_nothing_is_invented(env):
    _, sf, _ = env
    s = sf()
    assert annotate(s, "graphene coating battery lifespan") == []
    s.close()


def test_query_reports_entities_and_uses_their_synonyms_to_broaden(env):
    _, sf, _ = env
    s = sf()
    load_obo(s, OBO, "test")
    s.commit()
    s.close()
    c, pid = app_with(env, [SUPPORT_A])
    job = ask(c, pid, Q)
    assert {e["term_id"] for e in job["result"]["understanding"]["entities"]} >= {"T:0001"}
    queries = [r["query"] for r in job["result"]["plans"][0]["rounds"]]
    assert "graphene film" in queries or "cycle life" in queries                 # synonyms were used when evidence was thin
    assert "ontology terms recognised: graphene coating (T:0001)" in c.get(f"/api/v1/projects/{pid}/report").json()["markdown"]
