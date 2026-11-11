"""Remote workspace operations."""
import argparse
import os
import sqlite3
import time
from pathlib import Path

from .database import Database
from .providers import EuropePMC
from .research import ResearchEngine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["worker", "backup", "verify-backup"])
    parser.add_argument("--file", type=Path)
    args = parser.parse_args()
    path = Path(os.environ.get("ARES_DATABASE", "state/ares.db"))
    if args.command == "worker":
        engine = ResearchEngine(Database(path), EuropePMC())
        while True:
            if not engine.run_once():
                time.sleep(1)
    else:
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
