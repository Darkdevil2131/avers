"""Bounded deterministic research workflow with durable leases and citation snapshots."""
import json
import time

from .database import now
from .providers import ProviderError

STAGES = (
    {"id": "plan", "requires": [], "tool": "plan"},
    {"id": "retrieve", "requires": ["plan"], "tool": "project_search"},
    {"id": "audit", "requires": ["retrieve"], "tool": "citation_audit"},
    {"id": "report", "requires": ["audit"], "tool": "write_report"},
)


class ResearchEngine:
    def __init__(self, database, provider):
        self.database = database
        self.provider = provider

    def execute(self, run_id):
        dbs = self.database
        with dbs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            claimed = db.execute("""
                UPDATE run_state SET status='running', attempts=attempts+1,lease_until=?
                WHERE run_id=? AND cancelled=0 AND attempts<3
                AND (status='queued' OR (status='running' AND lease_until<?))
                RETURNING *
            """, (time.time() + 90, run_id, time.time())).fetchone()
            if claimed is None:
                return False
            run = dict(db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
            dbs.event(db, run_id, "plan", {"plan": STAGES, "attempt": claimed["attempts"],
                                         "mode": "deterministic", "max_sources": 10})
        try:
            if claimed["external"]:
                with dbs.connect() as db:
                    dbs.event(db, run_id, "external_search_started", {"provider": "Europe PMC"})
                try:
                    records = self.provider.search(run["question"])
                    with dbs.connect() as db:
                        for record in records:
                            dbs.add_source(db, run["project_id"], record, "research_worker")
                        dbs.event(db, run_id, "external_search_completed",
                                  {"provider": "Europe PMC", "count": len(records), "content": "metadata"})
                except ProviderError as exc:
                    with dbs.connect() as db:
                        dbs.event(db, run_id, "external_search_failed", {"message": str(exc)})

            with dbs.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                state = db.execute("SELECT * FROM run_state WHERE run_id=?", (run_id,)).fetchone()
                if state["cancelled"]:
                    db.execute("UPDATE run_state SET status='cancelled' WHERE run_id=?", (run_id,))
                    dbs.event(db, run_id, "cancelled", {})
                    return True
                passages = dbs.search(db, run["project_id"], run["question"])
                citations = []
                for passage in passages:
                    original = db.execute("SELECT text FROM sources WHERE id=?", (passage["source_id"],)).fetchone()[0]
                    if original[passage["start_offset"]:passage["end_offset"]] != passage["text"]:
                        raise ValueError("Citation integrity check failed")
                    citations.append({
                        **{k: v for k, v in passage.items() if k != "rank"},
                        "label": f"S{len(citations) + 1}", "quote": passage["text"],
                    })
                dbs.event(db, run_id, "retrieve", {"passages": len(citations),
                          "sources": len({c["source_id"] for c in citations})})
                dbs.event(db, run_id, "audit", {"exact_spans_checked": len(citations),
                          "scientific_support": "unverified"})
                report = {
                    "run_id": run_id, "question": run["question"],
                    "assessment": "inconclusive", "calibrated": False,
                    "summary": "Relevant passages were retrieved for review." if citations else
                               "The available project sources contain no matching passages.",
                    "citations": citations,
                    "limitations": [
                        "Lexical retrieval establishes relevance only.",
                        "Scientific support, study independence and context compatibility require review.",
                        "Europe PMC imports contain bibliographic metadata only.",
                    ],
                    "next_steps": [
                        "Review study methods, population or material, conditions, units and measured outcomes.",
                        "Add primary evidence and actively search for counterevidence.",
                    ],
                    "created_at": now(),
                }
                lines = ["# Research evidence report", "", run["question"], "",
                         "Assessment — inconclusive", "", report["summary"], ""]
                for citation in citations:
                    lines += [f"## [{citation['label']}] {citation['title']}", "",
                              citation["quote"], "", citation["url"],
                              f"Source SHA-256 {citation['digest']}", ""]
                lines += ["## Limitations", ""] + [f"- {x}" for x in report["limitations"]]
                db.execute("INSERT OR IGNORE INTO reports VALUES(?,?,?,?)",
                           (run_id, json.dumps(report), "\n".join(lines), now()))
                db.execute("UPDATE run_state SET status='completed',lease_until=0,error=NULL WHERE run_id=?", (run_id,))
                dbs.event(db, run_id, "report", {"status": "completed", "assessment": "inconclusive"})
                dbs.audit(db, run["project_id"], "research_worker", "run_completed", {"run_id": run_id})
            return True
        except Exception:
            with dbs.connect() as db:
                db.execute("UPDATE run_state SET status='failed',error='Research execution failed' WHERE run_id=?", (run_id,))
                dbs.event(db, run_id, "failed", {"message": "Research execution failed"})
            raise

    def run_once(self):
        with self.database.connect() as db:
            db.execute("""
                UPDATE run_state SET status='failed',error='Retry budget exhausted'
                WHERE status='running' AND lease_until<? AND attempts>=3
            """, (time.time(),))
            row = db.execute("""
                SELECT run_id FROM run_state WHERE cancelled=0 AND attempts<3
                AND (status='queued' OR (status='running' AND lease_until<?))
                ORDER BY rowid LIMIT 1
            """, (time.time(),)).fetchone()
        return self.execute(row["run_id"]) if row else False
