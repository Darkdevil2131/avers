"""Report generator. Every statement is tagged by origin: [SOURCE] from the document, [CALC] computed by an engine,
[HEURISTIC] rule-based extraction/inference, [HYPOTHESIS] unverified. Missing parts say why, never invented."""
from datetime import datetime, timezone

SECTIONS = [
    "Executive Summary", "Original Research Objective", "Research Context", "Documents Analyzed", "Evidence Collection Method",
    "Scientific Claims Extracted", "Supporting Evidence", "Contradictory Evidence", "Evidence Quality Assessment",
    "Methodology Review", "Mathematical Validation", "Statistical Validation", "Scientific Reasoning", "Knowledge Graph Findings",
    "Current Belief Assessment", "Research Limitations", "Identified Research Gaps", "Generated Hypotheses", "Hypothesis Evaluation",
    "Suggested Experiments", "Recommendations", "References", "Provenance", "Uncertainty and Confidence", "Reproducibility Information",
]


def _na(reason: str) -> str:
    return f"_Not available: {reason}._"


def generate(st: dict) -> str:
    doc, claims, routing = st["doc"], st["claims"], st["routing"]
    res = st.get("task_results", {})
    sec = {s: "" for s in SECTIONS}
    findings = [c for c in claims if c["kind"] == "finding"]
    stats = st.get("stat_results")
    problems = [r for r in (stats or {}).get("results", []) if r["status"] in ("inconsistent", "decision_error")]
    beliefs = st.get("beliefs", [])
    hyps = st.get("hypotheses", [])

    sec["Executive Summary"] = (
        f"Noesis analysed **{doc['filename']}** ({doc['n_pages']} page(s)). Routing: **{routing['mode']}** {routing['domains']}. "
        f"Extracted {len(findings)} finding-type claim(s) [HEURISTIC]. "
        + (f"Statistical recomputation found **{len(problems)}** inconsistent reported result(s) out of {stats['n_checked']} [CALC]. " if stats else "No statistical reports were found to recompute. ")
        + f"{len(beliefs)} belief(s) recorded; {sum(1 for b in beliefs if b['support_class'] == 'not_independently_verifiable')} of them have no independent external evidence. "
        + f"{len(hyps)} candidate hypothesis(es) generated (all **unverified**).")
    sec["Original Research Objective"] = f"Document title (extracted): _{doc['title']}_ [SOURCE]. No explicit user objective was supplied in this run."
    sec["Research Context"] = f"Domain routing scores: {routing['scores']} [HEURISTIC]."
    sec["Documents Analyzed"] = f"- {doc['filename']} — sha256 `{doc['sha256'][:16]}…` — {doc['n_pages']} page(s)"
    papers = st.get("papers", [])
    acq = {k: v for k, v in res.items() if k.startswith("acquire_")}
    sec["Evidence Collection Method"] = (
        "Metadata-first retrieval through official APIs only (no paywall circumvention). "
        + (f"Retrieved {len(papers)} unique external record(s). " if papers else "No external literature was retrieved. ")
        + "Connector status: " + ("; ".join(f"{k}: {v['status']}" for k, v in acq.items()) if acq else "no acquisition task ran (offline, no domain match, or no findings)") + ".")
    sec["Scientific Claims Extracted"] = "\n".join(
        f"- p.{c['page']} ({c['section']}): “{c['text']}” — language: {c['meta'].get('language')} [SOURCE; extraction HEURISTIC]" for c in findings[:25]) or _na("no finding-type claims detected")
    sup = [(b, e) for b in beliefs for e in b["evidence"] if e["stance"] == "supports" and e["group"] != "source_document"]
    con = [(b, e) for b in beliefs for e in b["evidence"] if e["stance"] == "contradicts"]
    sec["Supporting Evidence"] = "\n".join(f"- Belief {b['id']} ← {e['title'] or e['doi']} (grade {e['grade_label']}, design {e['design']}) [HEURISTIC stance]" for b, e in sup) or _na("no independent supporting evidence retrieved")
    sec["Contradictory Evidence"] = "\n".join(f"- Belief {b['id']} ← {e['title'] or e['doi']} (grade {e['grade_label']}) [HEURISTIC stance]" for b, e in con) or _na("none found (absence is not evidence of absence)")
    sec["Evidence Quality Assessment"] = ("Criteria: study design → peer-review status → sample size → retraction → independent replication (GRADE-inspired, unvalidated). Citation counts/journal prestige are NOT used.\n"
        + "\n".join(f"- Belief {b['id']}: {b['support_class']}; criteria per item: " + "; ".join(f"{e['title'][:40] or e['source']}: {[c['criterion'] + ' ' + c['effect'] for c in e['criteria']]}" for e in b["evidence"] if e["group"] != "source_document") for b in beliefs if any(e["group"] != "source_document" for e in b["evidence"])))
    sec["Methodology Review"] = (f"Causal-wording audit [HEURISTIC]: {st['causal']['n_causal_claims']} causal claim(s); "
        + ("; ".join(f"“{f['claim'][:80]}” — {f['issue']}" for f in st['causal']['flagged']) or "none flagged") if st.get("causal") else _na("causal audit did not run"))
    maths = st.get("math_results")
    sec["Mathematical Validation"] = ("\n".join(f"- `{r['equation']}` → **{r['verdict']}** {r.get('note', '')} [CALC, SymPy]" for r in maths["results"]) if maths else _na("no equation candidates detected"))
    grim_lines = [f"- Table p.{g['page']}: {g['n_impossible']} of {len(g['results'])} reported means are impossible for integer data (GRIM) [CALC]" for g in (stats or {}).get("grim_tables", [])]
    sec["Statistical Validation"] = ("\n".join(grim_lines) + "\n" if grim_lines else "") + ("\n".join(f"- {r['reported']} → computed p ∈ {r['computed_p_range']} → **{r['status']}** [CALC, SciPy]" for r in stats["results"]) if stats and stats["results"] else (_na("no statistical reports detected") if not grim_lines else ""))
    logic = st.get("logic")
    sec["Scientific Reasoning"] = (f"Contradictions among extracted claim triples: {logic['n_contradictions']} [HEURISTIC]. " + ("; ".join(logic["pairs"]) if logic["pairs"] else "") if logic else _na("fewer than two structured claims"))
    g = st.get("graph_summary", {})
    sec["Knowledge Graph Findings"] = (f"Nodes: {g.get('n_nodes')}, edges: {g.get('n_edges')}, entity relations: {g.get('n_entity_edges')}, open chains (gaps): {g.get('n_gaps')}, cross-domain entities: {g.get('cross_domain')}" if g else _na("graph not built"))
    sec["Current Belief Assessment"] = "\n".join(
        f"- Belief {b['id']}: “{b['claim_text'][:100]}” → **{b['assessment']}** (support class: {b['support_class']}; posterior {b['posterior']}; uncertainty {b['uncertainty']}; n_eff {b['n_effective']}; calibrated: false) flags={b['flags']}"
        for b in beliefs) or _na("no beliefs")
    lims = [c for c in claims if c["kind"] == "limitation"]
    sec["Research Limitations"] = ("Stated by the authors [SOURCE]:\n" + "\n".join(f"- p.{c['page']}: {c['text']}" for c in lims) if lims else "No author-stated limitations detected.") + "\n\nSystem limitations: rule-based extraction; lexical stance detection; uncalibrated belief pooling; small retrieval corpus; no OCR for scanned PDFs."
    gaps = st.get("gaps", [])
    sec["Identified Research Gaps"] = "\n".join(f"- {h['scientific_gap']}" for h in hyps) or _na("no graph gaps found in the available corpus")
    sec["Generated Hypotheses"] = "\n".join(f"- **{h['hypothesis_id']}** [HYPOTHESIS, status: {h['status']}] {h['statement']} (method: {h['generation_method']}; confidence: not assigned)" for h in hyps) or _na("none generated")
    sec["Hypothesis Evaluation"] = "\n".join(f"- {h['hypothesis_id']}: " + ", ".join(f"{c['check']}={'ok' if c['passed'] else 'FAIL'}" for c in h.get("verification", {}).get("checks", [])) for h in hyps) or _na("none")
    sec["Suggested Experiments"] = "\n".join(
        f"- **{h['hypothesis_id']}** (_proposal only, not executed_): {h['proposed_experiment'].get('design')}; n/group ≈ {h['proposed_experiment'].get('sample_size', {}).get('n_per_group')} under assumed d={h['proposed_experiment'].get('sample_size', {}).get('assumed_effect_size_d')} [CALC on ASSUMPTION]; success: {h['proposed_experiment'].get('success_criteria')}; failure: {h['proposed_experiment'].get('failure_criteria')}"
        for h in hyps if h.get("proposed_experiment")) or _na("none")
    recs = []
    if problems:
        recs.append("Re-check the flagged statistical results against raw data before relying on them.")
    if any(b["support_class"] == "not_independently_verifiable" for b in beliefs):
        recs.append("Several claims have only self-reported support; seek independent replication or external data.")
    if not papers:
        recs.append("Run again with network access/API keys so external evidence can be collected.")
    recs.append("Have a domain expert review all hypotheses before any experimental or clinical use.")
    sec["Recommendations"] = "\n".join(f"- {r}" for r in recs)
    sec["References"] = ("**Source document DOIs cited in its reference list** [SOURCE]: " + (", ".join(doc["dois"]) or "none detected") + "\n\n**Retrieved external records**:\n" + ("\n".join(f"- {p['title']} ({p.get('year')}) doi:{p['doi'] or 'n/a'} — {p['source']} — license: {p['license'] or 'unknown'}" for p in papers[:30]) or "none"))
    sec["Provenance"] = f"Original stored in object storage as `{doc['blob_key']}`. External records carry source, retrieval time and license fields. Job/task timeline:\n" + "\n".join(f"- {k}: {v['status']} ({v.get('duration_s', 0)}s){' — ' + v['error'] if v.get('error') else ''}" for k, v in res.items())
    sec["Uncertainty and Confidence"] = "No calibrated confidence values exist in this system yet. Belief posteriors are log-odds pooling with an *assumed* likelihood-ratio table and must not be read as probabilities of truth. Hypotheses carry confidence = null."
    sec["Reproducibility Information"] = f"Generated {datetime.now(timezone.utc).isoformat()} by Noesis 0.1.0. Extraction=rule_v1; evidence=evidence_v1; belief=log-odds-pooling v1; external APIs used: {sorted({p['source'] for p in papers}) or 'none'}. External results can change over time."
    out = ["# Noesis Scientific Report", ""]
    for i, s in enumerate(SECTIONS, 1):
        out += [f"## {i}. {s}", sec[s] or _na("not generated"), ""]
    return "\n".join(out)
