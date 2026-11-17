"""Operational status from the same database used by the queue."""
import importlib.util
import logging
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

HEARTBEAT_SECONDS = 5
STALE_SECONDS = 30


def reasoning_status():
    path = os.environ.get('ARES_REASONER_MODEL')
    if not path:
        return 'not_configured'
    if not Path(path).is_file():
        return 'model_missing'
    if importlib.util.find_spec('llama_cpp') is None:
        return 'runtime_missing'
    return 'configured'


def record_heartbeat(storage, worker_id):
    now = time.time()
    with storage.connect() as db:
        db.execute('''INSERT INTO worker_status(worker_id,last_seen,reasoning_status) VALUES(?,?,?)
                      ON CONFLICT(worker_id) DO UPDATE SET
                      last_seen=excluded.last_seen,reasoning_status=excluded.reasoning_status''',
                   (worker_id, now, reasoning_status()))
        db.execute('DELETE FROM worker_status WHERE last_seen<?', (now - 86400,))


class WorkerHeartbeat:
    def __init__(self, storage):
        self.storage = storage
        self.worker_id = str(uuid4())
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name='ares-heartbeat', daemon=True)

    def __enter__(self):
        # Fail startup if this role cannot publish to the queue's database.
        record_heartbeat(self.storage, self.worker_id)
        self.thread.start()
        return self

    def _run(self):
        while not self.stop.wait(HEARTBEAT_SECONDS):
            try:
                record_heartbeat(self.storage, self.worker_id)
            except Exception as exc:
                logging.getLogger('ares.worker').error('Worker heartbeat failed (%s)', type(exc).__name__)

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=45)
        try:
            with self.storage.connect() as db:
                db.execute('DELETE FROM worker_status WHERE worker_id=?', (self.worker_id,))
        except Exception as exc:
            logging.getLogger('ares.worker').error('Worker heartbeat cleanup failed (%s)', type(exc).__name__)


def runtime_status(storage, auto_process):
    with storage.connect() as db:
        db.execute('SELECT 1').fetchone()
        rows = db.execute('SELECT last_seen,reasoning_status FROM worker_status ORDER BY last_seen DESC').fetchall()
    if auto_process:
        return {'database': 'connected', 'queue_mode': 'inline', 'worker': 'in_process',
                'ready': True, 'reasoning': [reasoning_status()]}
    now = time.time()
    active = [row for row in rows if 0 <= now - row['last_seen'] <= STALE_SECONDS]
    return {'database': 'connected', 'queue_mode': 'db',
            'worker': 'connected' if active else 'stale' if rows else 'missing',
            'ready': bool(active), 'active_workers': len(active),
            'reasoning': sorted({row['reasoning_status'] for row in active})}
