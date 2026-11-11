"""Query mode (the flow both PDFs describe):
question -> Query Understanding -> seed hypotheses (testable claims) -> per-hypothesis retrieval (local corpus + live APIs)
-> evidence stance + grading -> beliefs -> evidence graph -> gap-driven hypotheses -> experiment proposals
-> coverage matrix + Veracity Gate -> report.
Seed hypotheses are search TARGETS (unverified); the verdicts come only from retrieved evidence."""
import re
from datetime import date

from sqlalchemy import select

from ..agents.base import TaskMessage
from ..agents.domain_agents import build_agents
from ..belief.engine import BeliefEngine
from ..corpus.index import CorpusIndex
from ..graph import evidence_graph as eg
from ..hypothesis import engine as hyp
from ..hypothesis import refine as hyp_refine
from ..hypothesis.experiment import plan as plan_experiment
from ..ingestion.claims import extract_triple
from ..llm import extract as llmx
from ..models import Hypothesis, Report
from ..planning.router import route
from ..verification.evidence import EvidenceInput, infer_design_from_text, lexical_stance
from ..verification.lineage import lineage_groups
from .engine_route import route_engines

_STOP = set("a an the of in on for to with by from at as is are was were be do does did how why what which who whom whose when where "
            "can could would should may might will it its this that these those and or not no than then there their between into under over "
            "about does effect effects impact role".split())
TYPE_CUES = [("temporal", r"\b(trend|trends|over time|has changed|have changed|in recent years|history of|evolution of|since 19\d\d|since 20\d\d)\b"),
             ("comparative", r"\b(vs|versus|compare|compared|better than|difference between)\b"),
             ("causal", r"\b(cause|causes|why|lead to|leads to|result in|mechanism|degrad\w+|affect\w*|increase\w*|decrease\w*|reduce\w*)\b"),
             ("exploratory", r"\b(what is known|state of|overview|review)\b")]


def understand(llm, question: str) -> dict:
    """Structured query: type, domains, concepts, constraints, time range. LLM when configured, rules otherwise."""
    q = question.strip()
    out = {"question": q, "method": "rules_v1", "constraints": "", "time_range": ""}
    if llm is not None and llm.available():
        d, err = llmx.safe(lambda: llm.complete_json(
            llmx.SYSTEM, 'Parse the research question. JSON only: {"question_type":"factual|comparative|causal|exploratory|temporal",'
            '"concepts":["2-6 key scientific concepts"],"constraints":"","time_range":""}\n<source>' + q + "</source>", max_tokens=400))
        if d and isinstance(d.get("concepts"), list) and d["concepts"]:
            out.update({"question_type": d.get("question_type") if d.get("question_type") in ("factual", "comparative", "causal", "exploratory", "temporal") else "factual",
                        "concepts": [str(c).lower()[:60] for c in d["concepts"][:6]], "constraints": str(d.get("constraints", ""))[:200],
                        "time_range": str(d.get("time_range", ""))[:50], "method": "llm_v1"})
    if "concepts" not in out:
        out["question_type"] = next((t for t, rx in TYPE_CUES if re.search(rx, q, re.I)), "factual")
        words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z\-]+", q.lower()) if w not in _STOP and len(w) > 2]
        grams, i = [], 0
        while i < len(words):
            grams.append(" ".join(words[i:i + 2]) if i + 1 < len(words) else words[i])
            i += 2
        out["concepts"] = grams[:6]
    out["routing"] = route(q + " " + " ".join(out["concepts"]))
    return out


def seed_hypotheses(llm, u: dict, max_n: int = 4) -> list:
    seeds = []
    if llm is not None and llm.available():
        d, err = llmx.safe(lambda: llm.complete_json(
            llmx.SYSTEM, f"Propose up to {max_n} distinct, testable hypotheses that would answer the question. JSON only: "
            '{"hypotheses":[{"subject":"","relation":"increases|decreases","object":"","rationale":""}]}\n<source>' + u["question"] + "</source>", max_tokens=800))
        for h in (d or {}).get("hypotheses", [])[:max_n] if isinstance(d, dict) else []:
            if isinstance(h, dict) and h.get("subject") and h.get("object") and h.get("relation") in ("increases", "decreases"):
                tr = {"subject": llmx._norm(str(h["subject"])), "relation": h["relation"], "object": llmx._norm(str(h["object"])), "negated": False, "method": "llm_v1"}
                seeds.append({"statement": f"{tr['subject']} {tr['relation']} {tr['object']}", "triple": tr, "rationale": str(h.get("rationale", ""))[:300], "origin": "llm_proposal"})
    if not seeds:
        t = extract_triple(re.sub(r"^(does|do|did|can|could|will|is|are)\s+", "", u["question"].strip().rstrip("?"), flags=re.I))
        if t:
            seeds.append({"statement": f"{t['subject']} {t['relation']} {t['object']}", "triple": t, "rationale": "parsed directly from the question", "origin": "rule"})
        c = u["concepts"]
        for i in range(0, max(0, len(c) - 1)):
            if len(seeds) + 2 > max_n:
                break
            # direction is not stated, so test BOTH directions as competing seeds; evidence can then confirm one and refute the other
            for rel in ("increases", "decreases"):
                st = f"{c[i]} {rel} {c[i + 1]}"
                if any(x["statement"].lower() == st.lower() for x in seeds):
                    continue
                seeds.append({"statement": st, "triple": {"subject": c[i], "relation": rel, "object": c[i + 1], "negated": False, "method": "rule_pair"},
                              "rationale": "concept pair from the question; direction not stated, the opposite direction is a competing seed", "origin": "rule_pair"})
        if not seeds and c:
            seeds.append({"statement": f"evidence about {c[0]}", "triple": None, "rationale": "single concept", "origin": "rule"})
    return seeds


def _paper_dict_from_corpus(p):
    from ..pipeline import _corpus_dict
    return _corpus_dict(p)


def _retrieve(s, settings, agents, domains, text: str, k: int = 8) -> tuple:
    papers, errs, known = [], [], set()
    idx = CorpusIndex(s)
    for dom in (domains or [None]):
        for p, sc in idx.search(text, k, domain=None if dom == "general" else dom):
            if p.content_hash not in known:
                known.add(p.content_hash)
                papers.append(_paper_dict_from_corpus(p))
    if not settings.offline:
        for dom in domains:
            res = agents[dom].execute(TaskMessage(task_id=f"q-{dom}", agent=f"{dom}_agent", objective="literature_search",
                                                  inputs={"queries": [text], "limit": 5, "budget": settings.crawl_budget_per_job},
                                                  required_operations=["literature_search"]))
            errs += res.errors
            for p in res.outputs.get("papers", []):
                if p["content_hash"] not in known:
                    known.add(p["content_hash"])
                    papers.append(p)
    return papers, errs


def coverage_status(b: dict) -> str:
    if b["assessment"] == "disputed" or b["support_class"] == "contradicted" or b["assessment"] == "contradicted":
        return "contradicted"
    if b["support_class"] == "directly_supported" or b["assessment"] == "supported":
        return "covered"
    if b["support_class"] == "partially_supported" or b["assessment"] == "conditionally_supported":
        return "partial"
    return "no_evidence"


def broaden(sd: dict, u: dict) -> list:
    """Alternative, broader retrieval queries for a seed hypothesis, best first: known ontology synonyms of terms in the question
    (same meaning, different words), then each side of the claim alone, then the question's key concepts."""
    alts = []
    for e in u.get("entities", []):
        alts += [x for x in e["synonyms"][:3]]
    if sd.get("triple"):
        alts += [sd["triple"]["subject"], sd["triple"]["object"]]
    alts += [c for c in u.get("concepts", []) if c]
    seen, out = {sd["statement"].lower()}, []
    for a in alts:
        if a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)
    return out


def veracity_gate(b: dict, settings) -> dict:
    ok = (b["n_effective"] >= settings.veracity_min_sources and (b["posterior"] or 0) >= settings.veracity_min_posterior
          and b["assessment"] in ("supported", "conditionally_supported"))
    return {"passed": ok, "rule": f">= {settings.veracity_min_sources} independent sources, posterior >= {settings.veracity_min_posterior}, "
                                  "assessment supported/conditionally_supported (a policy threshold, not a calibrated probability)"}


def run_query(sf, settings, project_id: int, question: str, connectors: dict, llm, *, job_id: int | None = None) -> dict:
    from ..pipeline import _belief_dicts, persist_papers
    s = sf()
    if llm is not None:
        llm.calls = 0
    u = understand(llm, question)
    from ..ontology.obo import annotate
    u["entities"] = annotate(s, question)          # [] unless an ontology file has been loaded; never guessed
    seeds = seed_hypotheses(llm, u)
    agents = build_agents(connectors)
    domains = [d for d in u["routing"]["domains"] if d in agents]
    if not domains and u["routing"]["mode"] == "unknown":
        domains = ["general"]          # scientific wording but no domain vocabulary matched: search broadly, unfiltered
    be = BeliefEngine(s)
    all_papers, errors, rows, points = {}, [], [], {}
    for sd in seeds:
        b = be.create(project_id, sd["statement"], assumptions=["seed hypothesis proposed to answer the question; its truth is decided only by retrieved evidence"],
                      reason=f"seed hypothesis ({sd['origin']}) for query")
        points[sd["statement"]] = []
        seed_rows, used_ids, n_ev, plan = {}, set(), 0, []

        def ingest(stored, round_no):
            nonlocal n_ev
            seed_rows.update({r.id: r for r in stored.values()})
            lin = lineage_groups({i: (r.meta or {}).get("authors") or [] for i, r in seed_rows.items()})
            for ch, row in stored.items():
                if row.id in used_ids or (row.meta or {}).get("design") == "non_evidence":
                    continue                  # grants, patents and datasets are context, never evidence of a scientific claim
                pt = (row.meta or {}).get("triples", [])
                passage = f"{row.title}. {row.abstract}"
                st = None
                if llm is not None and llm.available() and row.abstract.strip():
                    r_, err = llmx.safe(llmx.judge_stance, llm, sd["statement"], passage)
                    if r_:
                        st = {**r_, "relevance": None}
                    else:
                        errors.append({"llm": err})
                if st is None:
                    st = lexical_stance(sd["statement"], sd["triple"], passage, pt)
                if st["stance"] == "irrelevant":
                    continue
                used_ids.add(row.id)
                be.add_evidence(b.id, EvidenceInput(
                    title=row.title, source=row.source, doi=row.doi, design=(row.meta or {}).get("design") or infer_design_from_text(row.abstract),
                    stance=st["stance"], sample_size=(row.meta or {}).get("sample_size"), peer_reviewed=False if row.is_preprint else None, retracted=bool(row.retracted),
                    independence_group=lin[row.id], paper_id=row.id,
                    provenance={"stance_method": st["method"], "evidence_quote": st.get("evidence_quote", ""), "validated": False, "license": row.license,
                                "retrieval_round": round_no}),
                    f"retrieved paper ({row.source}); round {round_no}; stance heuristic/LLM, unvalidated")
                n_ev += 1
                yr = (row.meta or {}).get("year") or getattr(row, "year", None)
                if yr and st["stance"] in ("supports", "contradicts"):
                    points[sd["statement"]].append({"year": yr, "stance": st["stance"]})
            return lin

        text = f"{sd['triple']['subject']} {sd['triple']['object']}" if sd["triple"] else sd["statement"].replace(" is related to ", " ")
        papers, errs = _retrieve(s, settings, agents, domains, text)
        errors += errs
        stored = persist_papers(s, project_id, papers)
        all_papers.update(stored)
        ingest(stored, 0)
        plan.append({"round": 0, "query": text, "n_candidates": len(stored), "n_evidence_total": n_ev})
        # replanning: too little evidence -> broaden the query (each side of the claim alone, then single key terms) and retrieve again
        for rnd, alt in enumerate(broaden(sd, u)[: settings.max_replans], start=1):
            if n_ev >= settings.veracity_min_sources + 1:
                break
            papers, errs = _retrieve(s, settings, agents, domains, alt)
            errors += errs
            stored = persist_papers(s, project_id, papers)
            all_papers.update(stored)
            ingest(stored, rnd)
            plan.append({"round": rnd, "query": alt, "n_candidates": len(stored), "n_evidence_total": n_ev, "reason": "evidence below target; query broadened"})
        final_lin = lineage_groups({i: (r.meta or {}).get("authors") or [] for i, r in seed_rows.items()})
        be.relabel_groups(b.id, final_lin, "lineage recomputed over all retrieved papers")
        rows.append({"seed": sd, "belief_id": b.id, "n_candidates": len(seed_rows), "n_evidence": n_ev, "plan": plan})
    s.flush()
    beliefs = {b["id"]: b for b in _belief_dicts(s, project_id)}
    matrix = []
    for r in rows:
        b = beliefs[r["belief_id"]]
        matrix.append({"hypothesis": r["seed"]["statement"], "origin": r["seed"]["origin"], "status": coverage_status(b),
                       "gate": veracity_gate(b, settings), "belief_id": b["id"], "support_class": b["support_class"], "assessment": b["assessment"],
                       "posterior": b["posterior"], "n_effective": b["n_effective"],
                       "evidence": [e for e in b["evidence"] if e["group"] != "source_document"]})
    # gap-driven hypotheses from the graph (Overview: Hypothesis Generator) + verification + experiment plans
    G = eg.build_graph(s, project_id)
    E = eg.entity_digraph(G)
    corpus_texts = [f"{p.title}. {p.abstract}" for p in all_papers.values()]
    hyps = hyp.generate(E, [], corpus_texts, date.today().isoformat())
    hyp_refine.refine(llm, hyps)
    for h in hyps:
        v = hyp.verify(h, E, [])
        h["verification"], h["origin"] = v, "query"
        h["status"] = "dropped_by_critic" if h["status"] == "dropped_by_critic" else v["status"]
        if h["status"] == "requires_validation":
            h["proposed_experiment"] = plan_experiment(h)
        s.add(Hypothesis(project_id=project_id, job_id=job_id, payload=h, status=h["status"]))
    val_in = [{"hypothesis": m["hypothesis"], "n_effective": m["n_effective"], "status": m["status"], "gate_passed": m["gate"]["passed"],
               "designs": [e["design"] for e in m["evidence"] if e["stance"] == "supports"]} for m in matrix]
    engine_runs = route_engines(u["question_type"], list(all_papers.values()), points, val_in)
    from .report import generate
    md = generate(u, matrix, hyps, all_papers, errors, settings, llm, engine_runs)
    rep = Report(project_id=project_id, job_id=job_id, markdown=md)
    s.add(rep)
    s.commit()
    out = {"understanding": u, "coverage": [{k: v for k, v in m.items() if k != "evidence"} for m in matrix], "n_papers": len(all_papers),
           "n_gap_hypotheses": len(hyps), "engine_runs": engine_runs, "plans": [{"hypothesis": r["seed"]["statement"], "rounds": r["plan"]} for r in rows], "report_id": rep.id, "errors": errors[:20], "llm_calls": llm.calls if llm else 0}
    s.close()
    return out


def run_query_job(sf, settings, job_id: int, question: str, connectors: dict, llm=None):
    from ..models import Job, now
    s = sf()
    job = s.get(Job, job_id)
    job.status = "running"
    s.commit()
    try:
        res = run_query(sf, settings, job.project_id, question, connectors, llm, job_id=job_id)
        job = s.get(Job, job_id)
        job.status, job.result = "completed", res
    except Exception as e:
        s.rollback()
        job = s.get(Job, job_id)
        job.status, job.error = "failed", f"{type(e).__name__}: {e}"
    job.finished_at = now()
    s.commit()
    s.close()
