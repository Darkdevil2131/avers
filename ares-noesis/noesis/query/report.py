"""Query report: coverage matrix, Veracity-Gated answers, contradictions, gap-driven hypotheses, experiments. Origin-tagged."""
SYMBOL = {"covered": "✓ covered", "partial": "? partial", "contradicted": "⚠ contradicted/disputed", "no_evidence": "✗ no independent evidence"}


def generate(u, matrix, hyps, papers, errors, settings, llm, engine_runs=None) -> str:
    L = ["# Noesis Research Report", "", f"**Question:** {u['question']}", ""]
    L += ["## 1. Query understanding [" + ("LLM" if u["method"] == "llm_v1" else "HEURISTIC") + "]",
          f"- type: {u['question_type']}; domains: {u['routing']['domains'] or 'none matched'} ({u['routing']['mode']}); concepts: {u['concepts']}",
          f"- ontology terms recognised: {', '.join(e['label'] + ' (' + e['term_id'] + ')' for e in u.get('entities', [])) or 'none (no ontology loaded or no known term in the question)'}",
          f"- constraints: {u.get('constraints') or 'none extracted'}; time range: {u.get('time_range') or 'none extracted'}", ""]
    L += ["## 2. Answer (Veracity Gate applied)"]
    shown = [m for m in matrix if m["gate"]["passed"]]
    if shown:
        for m in shown:
            L.append(f"- **{m['hypothesis']}** is {m['assessment'].replace('_', ' ')} by {m['n_effective']} independent source(s) "
                     f"[{'; '.join((e['title'] or e['doi'])[:70] for e in m['evidence'] if e['stance'] == 'supports')}] (uncalibrated posterior {m['posterior']}).")
    else:
        L.append("**No answer is shown.** None of the candidate hypotheses passed the Veracity Gate, so the system refuses to state a conclusion. "
                 "What was found is listed below as leads, not findings.")
    L.append(f"- Gate rule: {matrix[0]['gate']['rule'] if matrix else 'n/a'}")
    L += ["", "## 3. Coverage matrix", "| Hypothesis | Status | Independent sources | Support class | Origin |", "|---|---|---|---|---|"]
    for m in matrix:
        L.append(f"| {m['hypothesis']} | {SYMBOL[m['status']]} | {m['n_effective']} | {m['support_class']} | {m['origin']} |")
    L += ["", "## 4. Evidence by hypothesis (supporting and opposing)"]
    for m in matrix:
        L.append(f"### {m['hypothesis']}")
        if not m["evidence"]:
            L.append("_No retrieved paper bore on this hypothesis. Absence of evidence in this corpus is not evidence of absence._")
        for e in m["evidence"]:
            q = next((c for c in [e.get("criteria")] if c), [])
            L.append(f"- **{e['stance']}** · {e['title']} · doi:{e['doi'] or 'n/a'} · {e['source']} · design: {e['design']} · grade: {e['grade_label']} "
                     f"[stance is unvalidated] — grading criteria: {'; '.join(c['criterion'] + ' ' + c['effect'] for c in q)}")
    L += ["", "## 5. Contradictions"]
    con = [m for m in matrix if m["status"] == "contradicted"]
    L += [f"- {m['hypothesis']}: evidence points both ways or against it (assessment: {m['assessment']})." for m in con] or ["_none detected_"]
    L += ["", "## 6. Knowledge gaps and new hypotheses (graph-driven; all unverified)"]
    for h in hyps:
        L.append(f"- **{h['hypothesis_id']}** [HYPOTHESIS, {h['status']}] {h['statement']} — gap: {h['scientific_gap']}")
    if not hyps:
        L.append("_No structural gaps found in the retrieved evidence graph._")
    L += ["", "## 7. Proposed experiments (not executed)"]
    for h in hyps:
        e = h.get("proposed_experiment")
        if e:
            L.append(f"- **{h['hypothesis_id']}**: {e['design']}; n/group ≈ {e['sample_size']['n_per_group']} (assumed d={e['sample_size']['assumed_effect_size_d']}); "
                     f"success: {e['success_criteria']}; failure: {e['failure_criteria']}")
    L += ["", "## Engine runs (what the reasoning engines did with the retrieved evidence)"]
    for r in engine_runs or []:
        if r["status"] == "ok":
            res = r["result"]
            detail = ", ".join(f"{k}={res[k]}" for k in ("n_checked", "n_problems", "n_causal_claims", "n_contradictions", "n_with_issues", "trend", "tau", "p_value") if k in res)
            if r["engine"] == "validation_engine":
                detail += "".join(f"; [{i['severity']}] {i['hypothesis']}: {i['message']}" for i in res.get("issues", [])[:8])
            L.append(f"- **{r['engine']}**{' (' + r['hypothesis'] + ')' if r.get('hypothesis') else ''}: ran on {r['n_inputs']} input(s); {detail or 'see job result'}")
        else:
            L.append(f"- **{r['engine']}**: {r['status']} — {r['reason']}")
    L += ["", "## 8. Sources retrieved"]
    for p in list(papers.values())[:40]:
        L.append(f"- {p.title} ({(p.meta or {}).get('year')}) doi:{p.doi or 'n/a'} — {p.source} — license: {p.license or 'unknown'}")
    L += ["", "## 9. Limitations and provenance",
          f"- Retrieval: local corpus + {'live APIs' if not settings.offline else 'no live APIs (offline)'}; {len(papers)} unique papers. Retrieval errors: {len(errors)}.",
          f"- Extraction/stance: {'LLM-assisted with verbatim-quote grounding' if llm is not None and llm.available() else 'rule-based heuristics (no LLM key configured): expect weak recall'}.",
          "- Evidence grades follow design/peer-review/sample-size/retraction; posteriors are log-odds pooling with an assumed likelihood table and are NOT calibrated probabilities.",
          "- A source count from a small corpus can be wrong in both directions; expert review is required before any use."]
    return "\n".join(L)
