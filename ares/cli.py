import argparse
import os
import sqlite3
import logging
import signal
import threading
from pathlib import Path
from .database import Database
from .providers import EuropePMC
from .research import ResearchEngine
from .runtime import WorkerHeartbeat
def run_worker(engine, stop=None):
    """Keep independent jobs moving after a failed job; back off on repeated errors."""
    stop = stop if stop is not None else threading.Event()
    failures = 0
    while not stop.is_set():
        try:
            worked = engine.run_once()
            failures = 0
            if not worked:
                stop.wait(1)
        except Exception as exc:
            failures = min(failures + 1, 6)
            delay = min(30, 2 ** (failures - 1))
            # Exception messages may contain source text, credentials or connection URLs.
            logging.getLogger('ares.worker').error('Worker iteration failed (%s); retry in %ss', type(exc).__name__, delay)
            stop.wait(delay)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve", "worker", "backup", "verify-backup"])
    parser.add_argument("--file", type=Path)
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        try:
            port = int(os.environ.get("PORT", "8000"))
        except ValueError:
            parser.error("PORT must be an integer")
        if not 1 <= port <= 65535:
            parser.error("PORT must be between 1 and 65535")
        uvicorn.run("ares.api:app_factory", factory=True, host="0.0.0.0", port=port)
        return
    path = os.environ.get("ARES_WORKER_DATABASE") or os.environ.get("ARES_DATABASE")
    if args.command == "worker" and not path:
        parser.error("Set ARES_WORKER_DATABASE or ARES_DATABASE to the same database used by the API")
    path = path or "state/ares.db"
    if args.command == "worker":
        engine = ResearchEngine(Database(path), EuropePMC())
        stop = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop.set())
        with WorkerHeartbeat(engine.database):
            run_worker(engine, stop)
    else:
        if path.startswith(("postgresql://","postgres://")):
            parser.error("Use pg_dump/pg_restore with the host backup operator for PostgreSQL")
        if args.file is None:
            parser.error("--file is required")
        if args.command == "backup":
            if args.file.exists():
                parser.error("Choose a new backup file")
            args.file.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as source, sqlite3.connect(args.file) as target:
                source.backup(target)
        with sqlite3.connect(f"file:{args.file}?mode=ro", uri=True) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SystemExit("Backup integrity check failed")
            if db.execute("PRAGMA foreign_key_check").fetchall():
                raise SystemExit("Backup foreign key check failed")
            print("Backup integrity verified")
if __name__ == "__main__":
    main()
