import json
import os
import re
import time
from .database import now
from .evidence import reviewed_finding_contexts, snapshot_reviewed_claim
from .collection import EvidenceCollector, evidence_signals, follow_up
from .retrieval import hybrid_search
from .agents import plan, extract, critique, propose, propose_exposure_test, proposal_critic
from uuid import uuid4
from .local_reasoner import suggest
from .prior_art import screen_prior_art, search_prior_art
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
            """, (time.time() + 360, run_id, time.time())).fetchone()
            if claimed is None:
                return False
            run = dict(db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
            dbs.event(db, run_id, "plan", {"plan": plan(run["question"]), "attempt": claimed["attempts"],
                                         "mode": "deterministic", "max_sources": 10})
        try:
            deadline=time.monotonic()+180
            def no_longer_owned():
                with dbs.connect() as check:
                    current=check.execute("SELECT * FROM run_state WHERE run_id=?",(run_id,)).fetchone()
                return (current['cancelled'] or current['status'] != 'running'
                        or current['attempts'] != claimed['attempts']
                        or current['lease_until'] <= time.time())

            def stopped():
                return time.monotonic() > deadline or no_longer_owned()

            def inference_timeout(cap):
                if stopped():
                    return None
                remaining = deadline - time.monotonic()
                return min(cap, remaining - 1) if remaining >= 2 else None

            def event(stage, payload):
                with dbs.connect() as db:
                    dbs.event(db, run_id, stage, payload)

            def store_sources(records):
                with dbs.connect() as db:
                    return [dbs.add_source(db, run["project_id"], record, "research_worker")["id"]
                            for record in records]

            def assess_passages():
                event("retrieval_started", {})
                with dbs.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    passages,retrieval = hybrid_search(dbs, db, run["project_id"], run["question"])
                    citations = []
                    pdf_documents = {}
                    for passage in passages:
                        original = db.execute("SELECT text FROM sources WHERE id=?", (passage["source_id"],)).fetchone()[0]
                        if original[passage["start_offset"]:passage["end_offset"]] != passage["text"]:
                            raise ValueError("Citation integrity check failed")
                        citation = {
                            **{k: v for k, v in passage.items() if k != "rank"},
                            "label": f"S{len(citations) + 1}", "quote": passage["text"],
                        }
                        if passage.get("origin") == "user_pdf":
                            source_id = passage["source_id"]
                            if source_id not in pdf_documents:
                                row = db.execute("SELECT metadata FROM documents WHERE source_id=?", (source_id,)).fetchone()
                                pdf_documents[source_id] = json.loads(row["metadata"])["locations"] if row else []
                            citation["pdf_pages"] = [
                                {"page": item["page"], "method": item["method"]}
                                for item in pdf_documents[source_id]
                                if item["start"] < passage["end_offset"] and passage["start_offset"] < item["end"]
                            ]
                        citations.append(citation)
                findings = extract(citations, run["question"])
                with dbs.connect() as db:
                    contexts = reviewed_finding_contexts(db, run["project_id"], findings)
                return citations, retrieval, findings, critique(findings, citations, contexts)

            collector = EvidenceCollector(self.provider, store_sources, event, stopped, bool(claimed["external"]))
            collection = collector.audit
            if claimed["external"]:
                event("external_search_started", {"provider": "Europe PMC"})
                collector.collect("primary_evidence", run["question"], "Collect primary literature for the question.", 2)

            if no_longer_owned():
                return False
            citations, retrieval, findings, criticism = assess_passages()
            if claimed["external"]:
                before = evidence_signals(findings, citations, criticism)
                choice = follow_up(run["question"], before) if callable(getattr(self.provider, "fulltext", None)) else None
                collection["adaptation"] = {"before": before}
                if choice and not stopped():
                    collector.collect(*choice, fetch_limit=4)
                    if no_longer_owned():
                        return False
                    if not stopped():
                        citations, retrieval, findings, criticism = assess_passages()
                    collection["adaptation"]["decision"] = choice[0]
                elif collector.references and not stopped():
                    event("planner_decision", {"strategy": "follow_citations",
                                              "reason": "Use the remaining full-text budget to check cited sources."})
                    collector.fetch(collector.references, 4)
                    if no_longer_owned():
                        return False
                    if not stopped():
                        citations, retrieval, findings, criticism = assess_passages()
                    collection["adaptation"]["decision"] = "follow_citations"
                else:
                    collection["adaptation"]["decision"] = "budget_exhausted" if stopped() else "no_follow_up"
                collection["adaptation"]["after"] = evidence_signals(findings, citations, criticism)
                collector.finish()

            event("memory_retrieval", retrieval)
            event("retrieve", {"passages": len(citations), "sources": len({c["source_id"] for c in citations})})
            event("audit", {"exact_spans_checked": len(citations), "tool": "citation_audit",
                            "scientific_support": "unverified"})
            event("reasoner_started", {"mode": "local model if configured", "network_tools": False})
            first_timeout = inference_timeout(90)
            inference = (
                suggest(run["question"], citations, timeout_seconds=first_timeout)
                if first_timeout is not None
                else {"status": "cancelled_or_budget_exhausted", "proposals": []}
            )
            rejected=[];proposals=[]
            def review_candidates(candidates):
                for candidate in candidates:
                    check=proposal_critic(candidate)
                    if check['accepted_as_candidate']:
                        proposals.append(dict(candidate,consistency_check=check))
                    else:
                        rejected.append({'candidate':candidate,'check':check})
            review_candidates(inference["proposals"])
            # One bounded correction attempt, only after an explicit opposition.
            # Do not pass generated text or untrusted source instructions as feedback.
            retry_timeout = None
            if not proposals and any(item['check']['direction_check']['status'] == 'potential_opposition'
                                     for item in rejected):
                retry_timeout = inference_timeout(30)
            if retry_timeout is not None:
                first = {k:v for k,v in inference.items() if k != 'proposals'}
                retry = suggest(run["question"], citations, retry_opposition=True,
                                timeout_seconds=retry_timeout)
                review_candidates(retry['proposals'])
                inference = {**retry, 'initial_attempt': first,
                             'retry': {'trigger': 'potential_opposition', 'attempts': 1,
                                       'scientific_validity': 'unvalidated'}}
            exposure_proposal = propose_exposure_test(findings, criticism)
            if exposure_proposal:
                proposals.append(exposure_proposal)
            if not proposals:proposals=propose(findings,run["question"])
            prior_search, related_records = (
                search_prior_art(run["question"], collection, self.provider, stopped, event)
                if proposals else ({"status": "no_proposal"}, [])
            )
            if claimed["external"]:
                collection["prior_art_search"] = prior_search
            for proposal in proposals:
                proposal["prior_art"] = screen_prior_art(
                    proposal, run["question"], citations, collector.records + related_records, collection, prior_search)
            criticism['rejected_proposals']=rejected
            with dbs.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                # Lock and fence the final transaction against cancellation and lease recovery.
                # PostgreSQL rechecks this predicate after waiting for a concurrent updater.
                owned = db.execute("""UPDATE run_state SET lease_until=lease_until
                    WHERE run_id=? AND status='running' AND cancelled=0
                    AND attempts=? AND lease_until>? RETURNING run_id""",
                    (run_id, claimed['attempts'], time.time())).fetchone()
                if owned is None:
                    return False
                reviewed_claim = snapshot_reviewed_claim(db, run["project_id"], run_id)
                assessment = reviewed_claim["assessment"] if reviewed_claim else "inconclusive"
                dbs.event(db,run_id,"reasoner_completed",{k:v for k,v in inference.items() if k!='proposals'})
                dbs.event(db,run_id,"extract",{"candidate_claims":len(findings),"methods":sorted({finding["method"] for finding in findings})})
                dbs.event(db,run_id,"critic",criticism)
                proposal_kinds = sorted({proposal['kind'] for proposal in proposals})
                dbs.event(db, run_id, "hypothesize", {
                    "proposals": len(proposals), "type": "follow-up candidates", "kinds": proposal_kinds,
                })
                report = {
                    "run_id": run_id, "question": run["question"], "retrieval":retrieval, "collection": collection,
                    "reasoner":{k:v for k,v in inference.items() if k!="proposals"},"findings":findings,"critique":criticism,"hypotheses":proposals,"plan":plan(run["question"]),
                    "assessment": assessment, "calibrated": False,
                    "summary": inference.get("answer") or ("Extracted observations: " + " ".join(f["statement"] for f in findings[:3]) if findings else "Relevant passages were retrieved for review." if citations else "The available project sources contain no matching passages."),
                    "summary_status": "exact source extract selected by local model" if inference.get("answer") else "extractive",
                    "citations": citations,
                    "limitations": [
                        "Lexical retrieval establishes relevance only.",
                        "Scientific support, study independence and context compatibility require review.",
                        "Only explicitly supported open licenses are ingested as full text; other results remain metadata.",
                        "Extracted findings are candidates, not independently validated claims.",
                    ],
                    "next_steps": [
                        "Review study methods, population or material, conditions, units and measured outcomes.",
                        "Add primary evidence and actively search for counterevidence.",
                    ],
                    "created_at": now(),
                }
                revision = os.environ.get("ARES_BUILD_REVISION", "")
                report["execution"] = {
                    "revision": revision.lower() if re.fullmatch(r"[a-fA-F0-9]{40}", revision) else None,
                    "attempt": claimed["attempts"], "external_collection_requested": bool(claimed["external"]),
                    "planner_policy": "evidence-triggered-follow-up-v1",
                }
                if any(f['method'] == 'context-weighted-sentence-reranker-v2' for f in findings):
                    from .retrieval import DENSE, RERANKER_MODEL
                    report['execution']['finding_reranker'] = {
                        'model': RERANKER_MODEL, 'snapshot_sha256': DENSE.reranker_artifact_hash,
                    }
                if reviewed_claim:
                    report["reviewed_claim"] = reviewed_claim
                lines = ["# Research evidence report", "", run["question"], "",
                         f"Assessment — {assessment}", "", report["summary"], ""]
                lines += ['## Source collection', '',
                          'Status: ' + collection['status'],
                          f"Metadata records: {collection['metadata_records']}; full texts stored: {collection['fulltext_stored']}; full texts attempted: {collection['fulltext_attempted']}",
                          collection['scope'], '']
                for error in collection['errors']:
                    identifier = f" {error['pmcid']}" if error.get('pmcid') else ''
                    lines += [f"- {error['stage']}{identifier}: {error['message']}"]
                    for attempt in error.get('attempts', []):
                        lines += [f"  - {attempt['provider']}: {attempt['reason'].replace('_', ' ')}"]
                for item in collection.get('fallbacks', []):
                    lines += [f"- {item['pmcid']} collected using a fallback provider."]
                    for attempt in item['attempts']:
                        lines += [f"  - {attempt['provider']}: {attempt['reason'].replace('_', ' ')}"]
                for item in collection.get('identity_unverified', []):
                    lines += [f"- {item['pmcid']}: article XML did not report a PMC identifier; identity needs review."]
                for entry in collection['queries']:
                    lines += [f"- Search ({entry['strategy']}): {entry['query']}"]
                    if entry.get('provider'):
                        lines += [f"  - Metadata provider: {entry['provider']}"]
                    if entry.get('fallback_used'):
                        lines += ['  - Europe PMC was unavailable or returned an invalid response; the fallback was used.']
                if collection['bounded']:
                    lines += ['Collection budget reached; the search is incomplete.']
                if collection.get('adaptation'):
                    adaptation = collection['adaptation']
                    before, after = adaptation['before'], adaptation['after']
                    lines += [
                        f"Follow-up decision: {adaptation['decision']}.",
                        f"Candidate study identifiers: {before['candidate_study_ids']} before, "
                        f"{after['candidate_study_ids']} after.",
                        f"Potential disagreements: {before['potential_disagreements']} before, "
                        f"{after['potential_disagreements']} after.",
                    ]
                for citation in citations:
                    lines += [f"## [{citation['label']}] {citation['title']}", "",
                              citation["quote"], "", citation["url"],
                              f"Source SHA-256 {citation['digest']}", ""]
                    if citation.get("pdf_pages"):
                        pages = ", ".join(f"{item['page']} ({item['method']})" for item in citation["pdf_pages"])
                        lines += [f"PDF pages: {pages}", ""]
                lines += ["## Extracted candidate findings", ""]+[f"- [{f['citation']}] {f['statement']}" for f in findings]
                for finding in findings:
                    for field, value in finding['reported_exposure'].items():
                        label = field.replace('_', ' ')
                        lines += [f"- [{finding['citation']}] Reported {label}: {value['quote']} "
                                  f"(characters {value['start_offset']}–{value['end_offset']})."]
                lines += ["## Review decision", "",criticism["reason"], ""]
                lines += ["## Limitations", ""] + [f"- {x}" for x in report["limitations"]]
                db.execute("INSERT OR IGNORE INTO reports VALUES(?,?,?,?)",
                           (run_id, json.dumps(report), "\n".join(lines), now()))
                db.execute("UPDATE run_state SET status='completed',lease_until=0,error=NULL WHERE run_id=?", (run_id,))
                dbs.event(db, run_id, "report", {"status": "completed", "assessment": assessment})
                dbs.audit(db, run["project_id"], "research_worker", "run_completed", {"run_id": run_id})
                db.execute("INSERT INTO research_memory VALUES(?,?,?,?,?,?,?)",(str(uuid4()),run["project_id"],run_id,json.dumps({"question":run["question"],"findings":findings,"source_ids":[c["source_id"] for c in citations]}),"pending",None,now()))
            return True
        except Exception:
            with dbs.connect() as db:
                owned = db.execute("""UPDATE run_state SET status='failed',lease_until=0,error='Research execution failed'
                    WHERE run_id=? AND status='running' AND cancelled=0
                    AND attempts=? AND lease_until>? RETURNING run_id""",
                    (run_id, claimed['attempts'], time.time())).fetchone()
                if owned:
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
