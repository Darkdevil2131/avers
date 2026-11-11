"""Durable job queue on the database (no Redis needed). Jobs survive restarts; a crashed worker's lease expires and
another worker re-claims the job. On PostgreSQL, claiming uses FOR UPDATE SKIP LOCKED so many workers can run in parallel."""
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select

from .connectors.sources import default_connectors
from .llm.client import LLMClient
from .models import Job, now


def enqueue(s, project_id: int, kind: str, payload: dict | None = None, document_id: int | None = None) -> Job:
    j = Job(project_id=project_id, document_id=document_id, kind=kind, payload=payload or {}, attempts=0)
    s.add(j)
    s.commit()
    return j


def claim(sf, settings, worker_id: str):
    from .db import retry_locked
    return retry_locked(lambda: _claim_once(sf, settings, worker_id))


def _claim_once(sf, settings, worker_id: str):
    """Atomically claim one job. The candidate is chosen with SELECT, then taken with a compare-and-set UPDATE
    (rowcount must be 1), so two workers can never both win the same job on any database, with or without row locks."""
    from sqlalchemy import update
    s = sf()
    try:
        for _ in range(50):
            t = datetime.now(timezone.utc)
            q = select(Job.id, Job.attempts).where(or_(Job.status == "queued", and_(Job.status == "running", Job.lease_until < t))).order_by(Job.id).limit(1)
            if s.get_bind().dialect.name == "postgresql":
                q = q.with_for_update(skip_locked=True)
            row = s.execute(q).first()
            if row is None:
                return None
            jid, attempts = row
            attempts = (attempts or 0) + 1
            if attempts > settings.max_attempts:
                n = s.execute(update(Job).where(Job.id == jid, Job.attempts.is_(None) | (Job.attempts == attempts - 1), Job.status.in_(["queued", "running"]))
                              .values(status="failed", attempts=attempts, finished_at=now(),
                                      error=f"gave up after {settings.max_attempts} attempts (worker crashed or timed out)")).rowcount
                s.commit()
                continue
            won = s.execute(update(Job).where(Job.id == jid, or_(Job.status == "queued", and_(Job.status == "running", Job.lease_until < t)),
                                              Job.attempts.is_(None) | (Job.attempts == attempts - 1))
                            .values(status="running", worker_id=worker_id, attempts=attempts, lease_until=t + timedelta(seconds=settings.lease_seconds))).rowcount
            s.commit()
            if won == 1:
                job = s.get(Job, jid)
                return job.id, job.kind, job.project_id, job.document_id, dict(job.payload or {})
            # lost the race: someone else took it between our SELECT and UPDATE; pick another
        return None
    finally:
        s.close()


class Heartbeat:
    """Extends a running job's lease while it works, so a legitimately long job is not re-claimed by another worker.
    A crashed worker stops heartbeating, its lease expires, and the job is re-claimed as before."""

    def __init__(self, sf, settings, job_id: int, interval: float | None = None):
        import threading
        self.sf, self.settings, self.job_id = sf, settings, job_id
        self.interval = interval if interval is not None else max(0.2, settings.lease_seconds / 3)
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def _beat(self):
        from sqlalchemy import update
        from .db import retry_locked

        def once():
            s = self.sf()
            try:
                s.execute(update(Job).where(Job.id == self.job_id, Job.status == "running")
                          .values(lease_until=datetime.now(timezone.utc) + timedelta(seconds=self.settings.lease_seconds)))
                s.commit()
            finally:
                s.close()
        retry_locked(once)

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                self._beat()
            except Exception:
                import logging
                logging.getLogger("noesis.worker").exception("heartbeat failed for job %s", self.job_id)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._t.join(timeout=5)


def execute(sf, store, settings, spec, connectors=None, llm=None):
    with Heartbeat(sf, settings, spec[0]):
        _execute(sf, store, settings, spec, connectors, llm)


def _execute(sf, store, settings, spec, connectors=None, llm=None):
    from . import pipeline
    from .corpus import store as corpus_store
    from .query.pipeline import run_query_job
    jid, kind, pid, did, payload = spec
    conns = connectors if connectors is not None else default_connectors(settings)
    if kind == "analyze_document":
        pipeline.analyze_document(sf, store, settings, jid, conns, llm)
    elif kind == "query":
        run_query_job(sf, settings, jid, payload["question"], conns, llm or LLMClient(settings))
    elif kind == "corpus_sync":
        s = sf()
        job = s.get(Job, jid)
        try:
            res = []
            for t in payload["topics"]:
                res += corpus_store.sync_topic(sf, conns, t, payload["domain"], payload["sources"], payload["limit"])
            job.status, job.result = "completed", {"runs": res}
        except Exception as e:
            job.status, job.error = "failed", f"{type(e).__name__}: {e}"
        job.finished_at = now()
        s.commit()
        s.close()
    else:
        s = sf()
        job = s.get(Job, jid)
        job.status, job.error, job.finished_at = "failed", f"unknown job kind '{kind}'", now()
        s.commit()


def run_once(sf, store, settings, worker_id="worker-1", connectors=None, llm=None) -> bool:
    spec = claim(sf, settings, worker_id)
    if spec is None:
        return False
    execute(sf, store, settings, spec, connectors, llm)
    return True


def run_forever(sf, store, settings, worker_id="worker-1", poll_s: float = 2.0, max_backoff: float = 60.0):
    """A transient error (DB restart, lock timeout, network) must never kill the worker: log, back off exponentially, continue."""
    import logging
    log = logging.getLogger("noesis.worker")
    backoff = poll_s
    while True:
        try:
            idle = not run_once(sf, store, settings, worker_id)
            backoff = poll_s
            if idle:
                time.sleep(poll_s)
        except Exception:
            log.exception("worker loop error; retrying in %.0fs", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
