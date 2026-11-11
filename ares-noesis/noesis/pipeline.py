"""End-to-end analysis pipeline: plan -> execute (failure-isolated) -> persist."""
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, func, select

from .agents.base import TaskMessage
from .agents.domain_agents import build_agents
from .belief.engine import BeliefEngine
from .connectors.base import ConnectorUnavailable
from .connectors.sources import default_connectors
from .engines import registry
from .graph import evidence_graph as eg
from .hypothesis import engine as hyp
from .hypothesis import refine as hyp_refine
from .hypothesis.experiment import plan as plan_experiment
from .ingestion.claims import extract_claims, extract_triple, triples_contradict
from .ingestion.parse import parse_document
from .corpus.index import CorpusIndex
from .llm.client import LLMClient
from .llm import extract as llmx
from .models import AuditLog, Belief, Claim, CorpusPaper, Document, ExternalPaper, Hypothesis, Job, Report, now
from .planning import planner
from .planning.router import route
from .report import generator
from .verification.evidence import SELF_GROUP, EvidenceInput, infer_design_from_text, lexical_stance

MAX_BELIEFS = 8


@dataclass
class Ctx:
    s: object
    project_id: int
    doc: Document
    settings: object
    agents: dict
    routing: dict
    claims: list
    parsed: object
    llm: object = None
    job_id: int | None = None
    state: dict = field(default_factory=dict)


def _audit(s, project_id, action, detail):
    s.add(AuditLog(project_id=project_id, actor="pipeline", action=action, detail=detail))


def _llm_enrich_claims(llm, parsed, claims_in: list) -> dict:
    """Add grounded LLM claims/triples on top of rule extraction (rules stay as the fallback). Returns a small audit dict."""
    info = {"used": False, "added": 0, "rejected": 0, "errors": []}
    if not llm.available():
        return info
    info["used"] = True
    by_sec: dict = {}
    for sent in parsed.sentences:
        if sent.section not in ("references", "front matter"):
            by_sec.setdefault((sent.page, sent.section), []).append(sent.text)
    for (page, section), sents in by_sec.items():
        for i in range(0, len(sents), 12):
            chunk = " ".join(sents[i:i + 12])[:12000]   # bound prompt size
            res, err = llmx.safe(llmx.extract_claims, llm, chunk)
            if err:
                info["errors"].append(err)
                if "budget" in err:
                    return info
                continue
            info["rejected"] += res["rejected"]
            for c in res["claims"]:
                match = next((x for x in claims_in if x["kind"] in ("finding", "statistical_report") and llmx._norm(x["text"]) == llmx._norm(c["quote"])), None)
                if match:
                    if c["triple"] and not match["meta"].get("triple"):
                        match["meta"]["triple"] = c["triple"]; info["added"] += 1
                    match["meta"]["language"] = c["language"] if c["language"] != "descriptive" else match["meta"].get("language", "descriptive")
                    match["meta"]["extraction"] = "rule_v1+llm_v1"
                else:
                    claims_in.append({"text": c["quote"], "page": page, "section": section, "kind": "finding",
                                      "meta": {"language": c["language"], "triple": c["triple"], "stats": [], "extraction": "llm_v1",
                                               "conditions": c["conditions"]}})
                    info["added"] += 1
    return info


# ---------------- handlers ----------------
def h_stat_check(ctx, t):
    reps = [r for c in ctx.claims for r in c["meta"].get("stats", [])]
    out = registry.ENGINES["statistical_engine"]["run"]({"operation": "check_reports", "reports": reps}) if reps else {"results": [], "n_checked": 0, "n_problems": 0}
    out["grim_tables"] = [{"page": c["page"], **registry.ENGINES["statistical_engine"]["run"]({"operation": "grim_table", "rows": c["meta"]["rows"]})}
                          for c in ctx.claims if c["kind"] == "table"]
    out["grim_tables"] = [g for g in out["grim_tables"] if g["applicable"]]
    ctx.state["stat_results"] = out
    return out


def h_math_check(ctx, t):
    eqs = [f"{c['meta']['lhs']} = {c['meta']['rhs']}" for c in ctx.claims if c["kind"] == "equation_candidate"]
    out = registry.ENGINES["math_engine"]["run"]({"operation": "check_equations", "equations": eqs})
    ctx.state["math_results"] = out
    return out


def h_logic_check(ctx, t):
    tr = [c["meta"]["triple"] for c in ctx.claims if c["meta"].get("triple")]
    pairs = [f"“{a['subject']} {a['relation']} {a['object']}” vs “{b['subject']} {b['relation']} {b['object']}”"
             for i, a in enumerate(tr) for b in tr[i + 1:] if triples_contradict(a, b)]
    out = {"n_contradictions": len(pairs), "pairs": pairs}
    ctx.state["logic"] = out
    return out


def h_causal_audit(ctx, t):
    text = " ".join(s.text for s in ctx.parsed.sentences)
    out = registry.ENGINES["causal_engine"]["run"]({"operation": "audit", "claims": [{**c["meta"], "text": c["text"], "page": c["page"]} for c in ctx.claims if c["kind"] == "finding"], "document_text": text})
    ctx.state["causal"] = out
    return out


def _queries(ctx, broaden=0):
    qs = []
    for c in ctx.claims:
        tr = c["meta"].get("triple")
        if tr and c["kind"] == "finding":
            qs.append(f"{tr['subject']} {tr['object']}" if not broaden else tr["subject"])
        if len(qs) >= 3:
            break
    return qs or [ctx.parsed.title]


def _corpus_dict(p: CorpusPaper) -> dict:
    return {"source": p.source, "source_id": p.source_id, "doi": p.doi, "title": p.title, "abstract": p.abstract, "license": p.license,
            "url": p.url, "retracted": p.retracted, "is_preprint": p.is_preprint, "content_hash": p.content_hash, "domain": p.domain,
            "design": p.design, "year": p.year, "authors": p.authors, "retrieved_at": p.retrieved_at.isoformat(), "origin": "local_corpus", "sample_size": p.sample_size}


def h_acquire(ctx, t):
    """Local corpus first (real harvested data, works offline), then live APIs through the domain agent if online."""
    dom = t.params["domain"]
    queries = _queries(ctx, t.params.get("broaden", 0))
    ctx.state.setdefault("papers", [])
    known = {p["content_hash"] for p in ctx.state["papers"]}
    n_local = 0
    idx = CorpusIndex(ctx.s)
    for q in queries:
        for p, score in idx.search(q, 5, domain=dom):
            if p.content_hash not in known:
                known.add(p.content_hash)
                ctx.state["papers"].append(_corpus_dict(p))
                n_local += 1
    out = {"n_local": n_local, "n_papers": n_local, "connectors": {}, "errors": []}
    if ctx.settings.offline:
        out["_status"] = "completed" if n_local else "partial"
        out["note"] = "offline mode: local corpus only"
        return out
    agent = ctx.agents[dom]
    msg = TaskMessage(task_id=t.id, agent=f"{dom}_agent", objective="literature_search",
                      inputs={"queries": queries, "limit": 5, "budget": ctx.settings.crawl_budget_per_job},
                      required_operations=["literature_search"])
    res = agent.execute(msg)
    n_live = 0
    for p in res.outputs.get("papers", []):
        if p["content_hash"] not in known:
            known.add(p["content_hash"])
            ctx.state["papers"].append(p)
            n_live += 1
    ctx.state.setdefault("agent_logs", {})[dom] = res.model_dump()
    out.update({"n_live": n_live, "n_papers": n_local + n_live, "connectors": res.outputs.get("connectors", {}), "errors": res.errors})
    out["_status"] = "partial" if (res.status in ("partial", "unavailable") and not (n_local or n_live)) else "completed"
    return out


def persist_papers(s, project_id: int, papers: list) -> dict:
    """Store retrieved papers per project (dedupe by content hash) with license + provenance + abstract triples."""
    from .ingestion.parse import split_sentences
    stored = {}
    for p in papers:
        row = s.scalars(select(ExternalPaper).where(ExternalPaper.project_id == project_id, ExternalPaper.content_hash == p["content_hash"])).first()
        if row is None:
            triples = [tr for sent in split_sentences(p["abstract"]) if (tr := extract_triple(sent))]
            row = ExternalPaper(project_id=project_id, source=p["source"], source_id=p["source_id"], doi=p["doi"], title=p["title"],
                                abstract=p["abstract"], license=p["license"], url=p["url"], retracted=p["retracted"],
                                is_preprint=p["is_preprint"], content_hash=p["content_hash"],
                                meta={"domain": p["domain"], "design": p["design"], "triples": triples, "year": p["year"],
                                      "authors": p["authors"][:5], "retrieved_at": p["retrieved_at"], "sample_size": p.get("sample_size")})
            s.add(row)
            s.flush()
        stored[p["content_hash"]] = row
    return stored


def h_verify(ctx, t):
    ctx.state["paper_rows"] = persist_papers(ctx.s, ctx.project_id, ctx.state.get("papers", []))
    return {"n_papers_stored": len(ctx.state["paper_rows"])}


def h_belief(ctx, t):
    s = ctx.s
    be = BeliefEngine(s)
    stat_bad = (ctx.state.get("stat_results") or {}).get("results", [])
    n = 0
    for c in [c for c in ctx.claims if c["kind"] == "finding"][:MAX_BELIEFS]:
        tr = c["meta"].get("triple")
        assum = ["conditions described in the source document"]
        b = be.create(ctx.project_id, c["text"], assumptions=assum, claim_id=c["id"], reason="claim extracted from source document")
        be.add_evidence(b.id, EvidenceInput(title="Source document (self-reported)", source="uploaded", design="self_reported",
                                            stance="supports", independence_group=SELF_GROUP,
                                            provenance={"document_id": ctx.doc.id, "page": c["page"]}), "author's own assertion; carries no independent weight")
        bad = [r for r in stat_bad if r["status"] in ("inconsistent", "decision_error") and any(r["reported"].startswith(f"{x['test']}({x['df1']}") for x in c["meta"].get("stats", []))]
        for r in bad:
            be.add_flag(b.id, f"reported statistic inconsistent: {r['reported']} (computed p range {r['computed_p_range']})", "statistical recomputation")
        for h, row in ctx.state.get("paper_rows", {}).items():
            pt = (row.meta or {}).get("triples", [])
            stance = None
            if ctx.llm is not None and ctx.llm.available() and (row.abstract or "").strip():
                r_, err = llmx.safe(llmx.judge_stance, ctx.llm, c["text"], f"{row.title}. {row.abstract}")
                if r_:
                    stance = {**r_, "relevance": None}
                else:
                    ctx.state.setdefault("llm_errors", []).append(err)
            if stance is None:
                stance = lexical_stance(c["text"], tr, f"{row.title}. {row.abstract}", pt)
            if stance["stance"] in ("irrelevant",) or (row.meta or {}).get("design") == "non_evidence":
                continue                      # grants, patents and datasets are context, never evidence of a scientific claim
            surname = ((row.meta or {}).get("authors") or [""])[0].split()[-1].lower() if (row.meta or {}).get("authors") else ""
            be.add_evidence(b.id, EvidenceInput(
                title=row.title, source=row.source, doi=row.doi, design=(row.meta or {}).get("design") or infer_design_from_text(row.abstract),
                stance=stance["stance"], sample_size=(row.meta or {}).get("sample_size"), peer_reviewed=False if row.is_preprint else None, retracted=bool(row.retracted),
                independence_group=f"author:{surname}" if surname else f"doi:{row.doi or row.id}", paper_id=row.id,
                provenance={"stance_method": stance["method"], "relevance": stance.get("relevance"), "evidence_quote": stance.get("evidence_quote", ""), "validated": False, "license": row.license}),
                f"external source {row.source} (stance heuristic, unvalidated)")
        n += 1
    return {"n_beliefs": n}


def _belief_dicts(s, project_id):
    from .models import EvidenceItem
    out = []
    for b in s.scalars(select(Belief).where(Belief.project_id == project_id, Belief.status != "superseded")):
        ev = [{"id": e.id, "title": e.title, "doi": e.doi, "source": e.source, "design": e.design, "stance": e.stance,
               "grade": e.grade, "grade_label": e.grade_label, "group": e.independence_group, "criteria": e.criteria}
              for e in s.scalars(select(EvidenceItem).where(EvidenceItem.belief_id == b.id, EvidenceItem.active.is_(True)))]
        out.append({"id": b.id, "claim_text": b.claim_text, "assessment": b.assessment, "support_class": b.support_class,
                    "posterior": b.posterior, "uncertainty": b.uncertainty, "n_effective": b.n_effective, "flags": b.flags,
                    "status": b.status, "version": b.version, "evidence": ev})
    return out


def h_graph(ctx, t):
    G = eg.build_graph(ctx.s, ctx.project_id)
    E = eg.entity_digraph(G)
    ctx.state["G"], ctx.state["E"] = G, E
    summ = {"n_nodes": G.number_of_nodes(), "n_edges": G.number_of_edges(), "n_entity_edges": E.number_of_edges(),
            "n_gaps": len(eg.find_gaps(E)), "cross_domain": len(eg.cross_domain_entities(E))}
    ctx.state["graph_summary"] = summ
    return summ


def h_hyp_generate(ctx, t):
    corpus = [c["text"] for c in ctx.claims] + [f"{p.title}. {p.abstract}" for p in ctx.state.get("paper_rows", {}).values()]
    ctx.state["hypotheses"] = hyp.generate(ctx.state["E"], ctx.state.get("beliefs", []), corpus, date.today().isoformat())
    info = hyp_refine.refine(ctx.llm, ctx.state["hypotheses"])
    return {"n_hypotheses": len(ctx.state["hypotheses"]), "critic": info}


def h_hyp_verify(ctx, t):
    for h in ctx.state["hypotheses"]:
        v = hyp.verify(h, ctx.state["E"], [])
        h["verification"] = v
        if h["status"] != "dropped_by_critic":
            h["status"] = v["status"]
    return {"statuses": [h["status"] for h in ctx.state["hypotheses"]]}


def h_experiment(ctx, t):
    for h in ctx.state["hypotheses"]:
        if h["status"] == "requires_validation":
            h["proposed_experiment"] = plan_experiment(h)
    return {"n_plans": sum(1 for h in ctx.state["hypotheses"] if h["proposed_experiment"])}


def h_report(ctx, t):
    s = ctx.s
    for h in ctx.state["hypotheses"]:
        s.add(Hypothesis(project_id=ctx.project_id, job_id=ctx.job_id, payload=h, status=h["status"]))
    md = generator.generate({
        "doc": {"filename": ctx.doc.filename, "n_pages": ctx.doc.n_pages, "sha256": ctx.doc.sha256, "title": ctx.parsed.title,
                "blob_key": ctx.doc.blob_key, "dois": ctx.parsed.dois},
        "claims": ctx.claims, "routing": ctx.routing, "task_results": ctx.state.get("task_results_so_far", {}),
        "stat_results": ctx.state.get("stat_results"), "math_results": ctx.state.get("math_results"), "logic": ctx.state.get("logic"),
        "causal": ctx.state.get("causal"), "papers": ctx.state.get("papers", []), "beliefs": _belief_dicts(s, ctx.project_id),
        "graph_summary": ctx.state.get("graph_summary"), "hypotheses": ctx.state["hypotheses"]})
    rep = Report(project_id=ctx.project_id, job_id=ctx.job_id, markdown=md)
    s.add(rep)
    s.flush()
    ctx.state["report_id"] = rep.id
    return {"report_id": rep.id}


HANDLERS = {"stat_check": h_stat_check, "math_check": h_math_check, "logic_check": h_logic_check, "causal_audit": h_causal_audit,
            "acquire_literature": h_acquire, "verify_evidence": h_verify, "belief_update": h_belief, "graph_build": h_graph,
            "hypothesis_generate": h_hyp_generate, "hypothesis_verify": h_hyp_verify, "experiment_plan": h_experiment, "report": h_report}


def analyze_document(session_factory, store, settings, job_id: int, connectors: dict | None = None, llm_client=None) -> dict:
    s = session_factory()
    job = s.get(Job, job_id)
    try:
        job.status = "running"
        s.commit()
        doc = s.get(Document, job.document_id)
        if doc is None or doc.project_id != job.project_id:
            raise ValueError("job document is outside the project")
        data = store.get(doc.blob_key)
        parsed = parse_document(doc.filename, data, settings.max_upload_mb * 1024 * 1024, settings.max_pages)
        doc.n_pages = parsed.n_pages
        doc.status = "parsed"
        old_ids = [c.id for c in s.scalars(select(Claim).where(Claim.document_id == doc.id))]
        for b in s.scalars(select(Belief).where(Belief.claim_id.in_(old_ids))) if old_ids else []:
            b.status, b.claim_id = "superseded", None  # keep audit history; detach from deleted claims
        s.flush()
        s.execute(delete(Claim).where(Claim.document_id == doc.id))
        rows = []
        extracted = extract_claims(parsed)
        llm = llm_client if isinstance(llm_client, LLMClient) else LLMClient(settings)
        llm.calls = 0  # per-document call budget
        llm_info = _llm_enrich_claims(llm, parsed, extracted)
        for c in extracted:
            row = Claim(document_id=doc.id, **c)
            s.add(row)
            rows.append(row)
        s.flush()
        claims = [{"id": r.id, "text": r.text, "page": r.page, "section": r.section, "kind": r.kind, "meta": r.meta} for r in rows]
        routing = route(" ".join([parsed.title] + [x["text"] for x in claims]))
        doc.meta = {**(doc.meta or {}), "title": parsed.title, "routing": routing, "dois": parsed.dois}
        feats = {"n_stats": sum(len(c["meta"].get("stats", [])) for c in claims) + sum(c["kind"] == "table" for c in claims),
                 "n_equations": sum(c["kind"] == "equation_candidate" for c in claims),
                 "n_triples": sum(bool(c["meta"].get("triple")) for c in claims),
                 "n_causal": sum(c["meta"].get("language") == "causal" for c in claims if c["kind"] == "finding"),
                 "n_findings": sum(c["kind"] == "finding" for c in claims)}
        conns = connectors if connectors is not None else default_connectors(settings)
        ctx = Ctx(s, doc.project_id, doc, settings, build_agents(conns), routing, claims, parsed, llm, job_id=job_id)
        ctx.state["llm_info"] = llm_info
        corpus_n = s.scalar(select(func.count(CorpusPaper.id))) or 0
        plan = planner.build_plan(feats, routing, offline=settings.offline, corpus_size=corpus_n)
        results: dict = {}
        ctx.state["task_results_so_far"] = results
        planner.execute(plan, HANDLERS, ctx, results, on_complete=planner.replan_acquisition)
        job.status = "completed" if all(r["status"] != "failed" for r in results.values()) else "completed_with_errors"
        job.result = {"llm": {**llm_info, "calls": llm.calls, "model": settings.llm_model if llm.available() else None}, "routing": routing, "features": feats, "plan": [t.id for t in plan], "tasks": results,
                      "report_id": ctx.state.get("report_id")}
        doc.status = "analyzed"
        _audit(s, doc.project_id, "analysis_finished", {"job": job.id, "status": job.status})
    except Exception as e:
        s.rollback()
        job = s.get(Job, job_id)
        job.status, job.error = "failed", f"{type(e).__name__}: {e}"
    job.finished_at = now()
    s.commit()
    out = job.result
    s.close()
    return out
