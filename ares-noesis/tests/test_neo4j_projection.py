from noesis.graph.neo4j_projection import project, statements
from tests.test_query import Q, SUPPORT_A, app_with, ask, paper


class FakeTx:
    def __init__(self, log):
        self.log = log

    def run(self, q, params):
        self.log.append((q, params))


class FakeSession:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute_write(self, fn):
        fn(FakeTx(self.log))


class FakeDriver:
    def __init__(self):
        self.log = []

    def session(self):
        return FakeSession(self.log)


def test_projection_is_idempotent_merge_only_and_carries_lineage(env):
    same_group = paper("Coated cells last longer", "We found that graphene coating increases battery lifespan across 40 coated cells.", "10.1/z", "Ana Lopez")
    c, pid = app_with(env, [SUPPORT_A, same_group])
    ask(c, pid, Q)
    _, sf, _ = env
    s = sf()
    st = statements(s, pid)
    assert all(q.startswith(("CREATE CONSTRAINT", "MERGE", "MATCH")) for q, _ in st)
    assert not any("CREATE (" in q or "DELETE" in q for q, _ in st)           # merge-only: re-running cannot duplicate or destroy
    assert any("EVIDENCED_BY" in q and p["stance"] == "supports" for q, p in st)
    assert any("SHARES_LINEAGE" in q for q, _ in st)                          # two papers by one author are linked
    assert st == statements(s, pid)                                           # deterministic
    d = FakeDriver()
    assert project(s, pid, d, batch=3)["statements"] == len(st) and len(d.log) == len(st)
    s.close()
