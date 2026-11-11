"""Reproduce first: do N parallel workers ever claim the same job? (select-then-update is racy without row locks, e.g. SQLite)."""
import threading
from collections import Counter

from noesis import worker
from noesis.config import Settings
from noesis.db import make_engine, make_session_factory
from noesis.models import Job, Project


def test_parallel_workers_never_double_claim(tmp_path):
    url = f"sqlite:///{tmp_path}/q.db"
    sf = make_session_factory(make_engine(url))
    s = sf()
    p = Project(name="x"); s.add(p); s.flush()
    for _ in range(40):
        s.add(Job(project_id=p.id, kind="noop", payload={}, attempts=0, status="queued"))
    s.commit()
    settings = Settings(database_url=url, lease_seconds=900)
    claimed, lock = [], threading.Lock()

    def work(name):
        wsf = make_session_factory(make_engine(url))      # each worker process has its own engine
        while True:
            spec = worker.claim(wsf, settings, name)
            if spec is None:
                return
            with lock:
                claimed.append(spec[0])

    errors = []
    old_hook = threading.excepthook
    threading.excepthook = lambda a: errors.append(repr(a.exc_value))
    ts = [threading.Thread(target=work, args=(f"w{i}",)) for i in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    threading.excepthook = old_hook
    assert not errors, f"worker threads crashed: {errors}"
    dupes = {k: v for k, v in Counter(claimed).items() if v > 1}
    assert not dupes, f"jobs claimed more than once: {dupes}"
    assert sorted(claimed) == list(range(1, 41))


def test_worker_loop_survives_transient_errors(monkeypatch):
    """A raising run_once must not terminate run_forever: it backs off and carries on."""
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("db restarting")
        raise KeyboardInterrupt                      # stop the infinite loop for the test

    monkeypatch.setattr(worker, "run_once", flaky)
    monkeypatch.setattr(worker.time, "sleep", lambda s: None)
    import pytest
    with pytest.raises(KeyboardInterrupt):
        worker.run_forever(None, None, Settings(), "w", poll_s=0.01)
    assert len(calls) == 3
