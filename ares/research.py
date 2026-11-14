import json
import time
from .database import now
from .evidence import reviewed_finding_contexts
from .providers import ProviderError
from .retrieval import hybrid_search
from .agents import plan, extract, critique, propose, proposal_critic
from uuid import uuid4
from .local_reasoner import suggest
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
            collection = {'requested': bool(claimed['external']), 'status': 'not_requested',
                          'queries': [], 'metadata_records': 0, 'fulltext_attempted': 0,
                          'fulltext_stored': 0, 'errors': [], 'bounded': False,
                          'scope': 'Bounded literature collection; absence of results is not evidence against a hypothesis.'}
            def stopped():
                with dbs.connect() as check:
                    current=check.execute("SELECT * FROM run_state WHERE run_id=?",(run_id,)).fetchone()
                return (current['cancelled'] or current['status'] != 'running'
                        or current['attempts'] != claimed['attempts']
                        or current['lease_until'] <= time.time() or time.monotonic()>deadline)
            if claimed["external"]:
                collection['status'] = 'collecting'
                with dbs.connect() as db:
                    dbs.event(db, run_id, "external_search_started", {"provider": "Europe PMC"})
                try:
                    with dbs.connect() as db:
                        local=dbs.search(db,run["project_id"],run["question"],limit=3)
                    objective=plan(run["question"])
                    query=run["question"]
                    strategy="primary_evidence"
                    if local:
                        query=" ".join(objective["search_terms"][:5])+" AND (replication OR \"no effect\" OR contradiction)"
                        strategy="counterevidence"
                    with dbs.connect() as db:
                        dbs.event(db,run_id,"planner_decision",{"strategy":strategy,"query":query,"reason":"Project already contains matching passages; search for counterevidence" if local else "No matching project passages; collect primary evidence"})
                    collection['queries'].append({'query': query, 'strategy': strategy})
                    records = list(self.provider.search(query))
                    if len(records)<2 and hasattr(self.provider,'fulltext') and not stopped():
                        broadened=" OR ".join(objective["search_terms"][:4])
                        with dbs.connect() as db:
                            dbs.event(db,run_id,"planner_decision",{"strategy":"broaden_search","query":broadened,"reason":"First search returned fewer than two records"})
                        collection['queries'].append({'query': broadened, 'strategy': 'broaden_search'})
                        try:
                            records.extend(self.provider.search(broadened))
                        except ProviderError as exc:
                            # Preserve useful first-search results if the broader request fails.
                            collection['errors'].append({'stage':'broaden_search','message':str(exc)[:300]})
                    records = list({record['url']: record for record in records}.values())
                    collection['metadata_records'] = len(records)
                    with dbs.connect() as db:
                        for record in records:
                            dbs.add_source(db, run["project_id"], record, "research_worker")
                        dbs.event(db, run_id, "external_search_completed",
                                  {"provider": "Europe PMC", "count": len(records), "content": "metadata"})
                    eligible=list(dict.fromkeys(r.get("pmcid") for r in records if r.get("is_open_access") and r.get("pmcid")))
                    collection['bounded'] = len(eligible) > 2
                    frontier=[(p,0) for p in eligible[:2]]
                    seen=set()
                    while frontier and len(seen)<4:
                        if stopped():
                            collection['bounded'] = True
                            break
                        pmcid,depth=frontier.pop(0)
                        if pmcid in seen:continue
                        seen.add(pmcid)
                        collection['fulltext_attempted'] += 1
                        with dbs.connect() as db:
                            dbs.event(db,run_id,"spider_fetch",{"pmcid":pmcid,"depth":depth,"source":"Europe PMC open-access API"})
                        try:
                            document=self.provider.fulltext(pmcid)
                            if depth<1:
                                frontier.extend((ref,depth+1) for ref in document["document"]["references"][:2] if ref not in seen)
                            with dbs.connect() as db:
                                source=dbs.add_source(db,run["project_id"],document,"research_worker")
                                collection['fulltext_stored'] += 1
                                dbs.event(db,run_id,"document_ingested",{"source_id":source["id"],"pmcid":pmcid,"characters":len(document["text"]),"license":document["license_status"]})
                        except ProviderError as exc:
                            collection['errors'].append({'stage':'fulltext','pmcid':pmcid,'message':str(exc)[:300]})
                            with dbs.connect() as db:dbs.event(db,run_id,"document_rejected",{"pmcid":pmcid,"message":str(exc)})
                    collection['bounded'] |= any(p not in seen for p, _ in frontier)
                except ProviderError as exc:
                    collection['errors'].append({'stage':'search','message':str(exc)[:300]})
                    with dbs.connect() as db:
                        dbs.event(db, run_id, "external_search_failed", {"message": str(exc)})
                if collection['errors'] or collection['bounded']:
                    collection['status'] = 'partial' if collection['metadata_records'] else 'unavailable'
                elif collection['fulltext_stored']:
                    collection['status'] = 'collected'
                else:
                    collection['status'] = 'metadata_only' if collection['metadata_records'] else 'no_results'
                with dbs.connect() as db:
                    dbs.event(db, run_id, 'collection_summary', collection)
            with dbs.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                state = db.execute("SELECT * FROM run_state WHERE run_id=?", (run_id,)).fetchone()
                if state['attempts'] != claimed['attempts'] or state['lease_until'] <= time.time():
                    return False
                if state["cancelled"]:
                    db.execute("UPDATE run_state SET status='cancelled' WHERE run_id=?", (run_id,))
                    dbs.event(db, run_id, "cancelled", {})
                    return True
                passages,retrieval = hybrid_search(dbs, db, run["project_id"], run["question"])
                dbs.event(db,run_id,"memory_retrieval",retrieval)
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
                dbs.event(db, run_id, "audit", {"exact_spans_checked": len(citations), "tool":"citation_audit",
                          "scientific_support": "unverified"})
            findings=extract(citations,run["question"])
            with dbs.connect() as db:
                contexts = reviewed_finding_contexts(db, run['project_id'], findings)
                dbs.event(db,run_id,"reasoner_started",{"mode":"local model if configured","network_tools":False})
            criticism=critique(findings,citations,contexts)
            inference=suggest(run["question"],citations) if not stopped() else {"status":"cancelled_or_budget_exhausted","proposals":[]}
            candidates=inference["proposals"]
            rejected=[];proposals=[]
            for candidate in candidates:
                check=proposal_critic(candidate)
                if check['accepted_as_candidate']:
                    proposals.append(dict(candidate,consistency_check=check))
                else:rejected.append({'candidate':candidate,'check':check})
            if not proposals:proposals=propose(findings,run["question"])
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
                dbs.event(db,run_id,"reasoner_completed",{k:v for k,v in inference.items() if k!='proposals'})
                dbs.event(db,run_id,"extract",{"candidate_claims":len(findings),"methods":sorted({finding["method"] for finding in findings})})
                dbs.event(db,run_id,"critic",criticism)
                dbs.event(db,run_id,"hypothesize",{"proposals":len(proposals),"type":"model candidates" if inference["status"]=="completed" else "replication candidates"})
                report = {
                    "run_id": run_id, "question": run["question"], "retrieval":retrieval, "collection": collection,
                    "reasoner":{k:v for k,v in inference.items() if k!="proposals"},"findings":findings,"critique":criticism,"hypotheses":proposals,"plan":plan(run["question"]),
                    "assessment": "inconclusive", "calibrated": False,
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
                lines = ["# Research evidence report", "", run["question"], "",
                         "Assessment — inconclusive", "", report["summary"], ""]
                lines += ['## Source collection', '',
                          'Status: ' + collection['status'],
                          f"Metadata records: {collection['metadata_records']}; full texts stored: {collection['fulltext_stored']}; full texts attempted: {collection['fulltext_attempted']}",
                          collection['scope'], '']
                lines += [f"- {error['stage']}: {error['message']}" for error in collection['errors']]
                lines += [f"- Search ({entry['strategy']}): {entry['query']}" for entry in collection['queries']]
                if collection['bounded']:
                    lines += ['Collection budget reached; the search is incomplete.']
                for citation in citations:
                    lines += [f"## [{citation['label']}] {citation['title']}", "",
                              citation["quote"], "", citation["url"],
                              f"Source SHA-256 {citation['digest']}", ""]
                lines += ["## Extracted candidate findings", ""]+[f"- [{f['citation']}] {f['statement']}" for f in findings]
                lines += ["## Review decision", "",criticism["reason"], ""]
                lines += ["## Limitations", ""] + [f"- {x}" for x in report["limitations"]]
                db.execute("INSERT OR IGNORE INTO reports VALUES(?,?,?,?)",
                           (run_id, json.dumps(report), "\n".join(lines), now()))
                db.execute("UPDATE run_state SET status='completed',lease_until=0,error=NULL WHERE run_id=?", (run_id,))
                dbs.event(db, run_id, "report", {"status": "completed", "assessment": "inconclusive"})
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
