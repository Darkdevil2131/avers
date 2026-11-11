"""noesis_mcp: tools for investigating research questions/papers with Noesis (evidence grading, beliefs, hypotheses, engines).

Design notes (per MCP best practices): action-oriented `noesis_*` names; read-only vs write annotations; pagination metadata on lists;
markdown (default) or JSON output; responses truncated with guidance; long work is a job (start -> poll), never a blocking call."""
import asyncio
import json
from enum import Enum
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from .client import NoesisAPIError, NoesisClient

CHARACTER_LIMIT = 25000
TERMINAL = {"completed", "completed_with_errors", "failed"}

RO = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
COMPUTE = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
WRITE_IDEMPOTENT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
EXTERNAL = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)

INSTRUCTIONS = (
    "Noesis grades scientific evidence. Typical flow: noesis_create_project -> noesis_ask_question (or noesis_upload_text_document + "
    "noesis_analyze_document) -> noesis_wait_for_job -> noesis_get_report / noesis_get_beliefs / noesis_list_hypotheses. "
    "Evidence stances are heuristic or LLM judgments and belief posteriors are NOT calibrated probabilities: treat results as leads with provenance, "
    "not verified facts. Hypotheses are unverified. Standalone engine tools (noesis_check_*, noesis_meta_analysis, noesis_sample_size, "
    "noesis_simulate_orbit) compute exact results and need no project.")


class Fmt(str, Enum):
    markdown = "markdown"
    json = "json"


class _In(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class Page(_In):
    limit: int = Field(20, ge=1, le=50, description="Items to return (1-50)")
    offset: int = Field(0, ge=0, description="Items to skip, for pagination")
    response_format: Fmt = Field(Fmt.markdown, description="'markdown' (readable) or 'json' (structured)")


class ProjectRef(_In):
    project_id: int = Field(..., ge=1, description="Project id from noesis_list_projects or noesis_create_project")


class CreateProjectIn(_In):
    name: str = Field(..., min_length=1, max_length=200, description="Project name, e.g. 'Perovskite degradation review'")


class UploadTextIn(ProjectRef):
    filename: str = Field(..., pattern=r"^[^/\\]+\.txt$", max_length=200, description="Plain-text paper name ending in .txt, e.g. 'my_paper.txt'")
    text: str = Field(..., min_length=50, max_length=2_000_000, description="Full paper text. Use section headings like 'Abstract', 'Methods', 'Results', 'References' on their own lines.")


class AnalyzeIn(ProjectRef):
    document_id: int = Field(..., ge=1, description="Document id returned by noesis_upload_text_document")


class AskIn(ProjectRef):
    question: str = Field(..., min_length=8, max_length=1000, description="Research question, e.g. 'Does graphene coating increase battery lifespan?'")


class JobIn(_In):
    job_id: int = Field(..., ge=1, description="Job id from noesis_ask_question / noesis_analyze_document")


class WaitIn(JobIn):
    timeout_seconds: int = Field(30, ge=1, le=120, description="Max seconds to wait before returning the current state (job keeps running)")


class ClaimsIn(ProjectRef, Page):
    kind: Optional[str] = Field(None, pattern="^(finding|statistical_report|limitation|equation_candidate|table)$", description="Filter by claim kind")


class BeliefsIn(ProjectRef, Page):
    assessment: Optional[str] = Field(None, description="Filter, e.g. supported, conditionally_supported, disputed, contradicted, insufficient_evidence")


class BeliefRef(_In):
    belief_id: int = Field(..., ge=1, description="Belief id from noesis_get_beliefs")


class FeedbackIn(BeliefRef):
    action: str = Field(..., pattern="^(dispute|invalidate|restore)$", description="dispute = mark contested; invalidate = reject the belief; restore = return to an earlier version")
    reason: str = Field(..., min_length=3, max_length=500, description="Why (recorded in the audit trail)")
    version: Optional[int] = Field(None, ge=1, description="Required for restore: version number from noesis_get_belief_history")


class HypIn(ProjectRef, Page):
    status: Optional[str] = Field(None, description="Filter, e.g. requires_validation, likely_already_described, conflicts_with_existing_evidence, dropped_by_critic")


class ReportIn(ProjectRef):
    max_chars: int = Field(20000, ge=1000, le=CHARACTER_LIMIT, description="Truncate the report to this many characters")


class SearchIn(Page):
    query: str = Field(..., min_length=1, max_length=500, description="Topic words, e.g. 'perovskite humidity degradation'")


class HarvestIn(_In):
    topics: list[str] = Field(..., min_length=1, max_length=10, description="Search topics to harvest papers for")
    domain: str = Field(..., pattern="^(medicine|technology|space)$", description="Domain agent that classifies the evidence")
    sources: list[str] = Field(default_factory=lambda: ["openalex", "arxiv", "crossref", "europepmc"], description="Sources, e.g. openalex, arxiv, crossref, europepmc, pubmed, clinicaltrials, semanticscholar, doaj")
    limit: int = Field(100, ge=1, le=1000, description="Max papers per source per topic")


class StatReport(_In):
    test: str = Field(..., pattern="^(t|F|chi2|r)$", description="Test type")
    stat: str = Field(..., pattern=r"^-?\d*\.?\d+$", description="Reported statistic exactly as printed, e.g. '2.10'")
    df1: str = Field(..., pattern=r"^\d+(\.\d+)?$", description="First degrees of freedom, e.g. '28'")
    df2: Optional[str] = Field(None, pattern=r"^\d+$", description="Second df (F tests only)")
    op: str = Field(..., pattern="^[<=>]$", description="Comparison reported for p: '<', '=' or '>'")
    p: str = Field(..., pattern=r"^\d*\.?\d+$", description="Reported p value exactly as printed, e.g. '.045'")


class StatsIn(_In):
    reports: list[StatReport] = Field(..., min_length=1, max_length=50, description="Reported test results to recompute")


class MetaIn(_In):
    effects: list[float] = Field(..., min_length=2, max_length=500, description="Effect sizes, one per study")
    standard_errors: list[float] = Field(..., min_length=2, max_length=500, description="Standard error of each effect (same order, all > 0)")
    model: str = Field("random", pattern="^(fixed|random)$", description="'random' (DerSimonian-Laird) or 'fixed' effects")


class SampleIn(_In):
    effect_size_d: float = Field(..., gt=0, le=5, description="Expected standardized effect (Cohen's d), e.g. 0.5")
    alpha: float = Field(0.05, gt=0, lt=0.5, description="Two-sided significance level")
    power: float = Field(0.8, gt=0.5, lt=1, description="Desired power")


class GrimIn(_In):
    mean: str = Field(..., pattern=r"^-?\d+\.\d+$", description="Reported mean exactly as printed, e.g. '5.19'")
    n: int = Field(..., ge=2, le=100000, description="Sample size of integer-valued data (e.g. Likert items)")


class DimsIn(_In):
    lhs: str = Field(..., max_length=300, description="Left side, e.g. 'E'")
    rhs: str = Field(..., max_length=300, description="Right side, e.g. 'm*v**2/2' (explicit * required)")
    units: dict[str, str] = Field(..., description="Unit for every symbol, e.g. {'E':'J','m':'kg','v':'m/s'}")


class EqIn(_In):
    lhs: str = Field(..., max_length=300, description="Left side expression, e.g. '(a+b)^2'")
    rhs: str = Field(..., max_length=300, description="Right side expression, e.g. 'a^2+2*a*b+b^2'")


class OrbitIn(_In):
    position_m: list[float] = Field(..., min_length=3, max_length=3, description="Initial position [x,y,z] in metres from Earth's centre")
    velocity_mps: list[float] = Field(..., min_length=3, max_length=3, description="Initial velocity [vx,vy,vz] in m/s")
    duration_s: float = Field(..., gt=0, le=1e7, description="Propagation time in seconds")


def _j(o: Any) -> str:
    return json.dumps(o, indent=2, default=str)


def _clip(text: str, hint: str = "Use limit/offset or a filter to narrow the result.") -> str:
    if len(text) <= CHARACTER_LIMIT:
        return text
    return text[:CHARACTER_LIMIT] + f"\n\n[truncated at {CHARACTER_LIMIT} characters. {hint}]"


def _page(items: list, p: Page) -> dict:
    chunk = items[p.offset:p.offset + p.limit]
    more = p.offset + len(chunk) < len(items)
    return {"total": len(items), "count": len(chunk), "offset": p.offset, "items": chunk, "has_more": more,
            "next_offset": p.offset + len(chunk) if more else None}


def _md_belief(b: dict) -> str:
    ev = [e for e in b["evidence"] if e["group"] != "source_document"]
    lines = [f"### Belief {b['id']}: {b['claim_text'][:200]}",
             f"- assessment: **{b['assessment']}** · support class: {b['support_class']} · independent sources: {b['n_effective']} · uncertainty: {b['uncertainty']} "
             f"· posterior {b['posterior']} (uncalibrated)" + (f" · status: {b['status']}" if b["status"] != "active" else "")]
    lines += [f"- ⚠ {f}" for f in b["flags"]]
    lines += [f"  - {e['stance']} · {e['title'][:90] or e['doi']} · {e['source']} · design {e['design']} · grade {e['grade_label']}" for e in ev] or ["  - no independent evidence"]
    return "\n".join(lines)


def create_server(client: NoesisClient | None = None) -> MCPServer:
    nc = client or NoesisClient()
    mcp = MCPServer("noesis_mcp", instructions=INSTRUCTIONS)

    async def guarded(coro):
        try:
            return await coro
        except NoesisAPIError as e:
            return f"Error: {e}"

    # ---------------- projects, documents, jobs ----------------
    @mcp.tool(name="noesis_list_projects", annotations=ToolAnnotations(title="List projects", **RO.model_dump(exclude={"title"})))
    async def noesis_list_projects() -> str:
        """List the Noesis projects you can access (id and name)."""
        async def go():
            ps = await nc.request("GET", "/projects")
            return "\n".join(f"- {p['id']}: {p['name']}" for p in ps) or "No projects yet. Create one with noesis_create_project."
        return await guarded(go())

    @mcp.tool(name="noesis_create_project", annotations=WRITE)
    async def noesis_create_project(params: CreateProjectIn) -> str:
        """Create a project (a workspace holding documents, evidence, beliefs, hypotheses and reports). Returns its id."""
        async def go():
            p = await nc.request("POST", "/projects", json={"name": params.name})
            return f"Created project {p['id']} ({p['name']})."
        return await guarded(go())

    @mcp.tool(name="noesis_upload_text_document", annotations=WRITE)
    async def noesis_upload_text_document(params: UploadTextIn) -> str:
        """Upload a paper as plain text (.txt) to a project. Next: noesis_analyze_document. (PDF upload is available through the REST API/UI.)"""
        async def go():
            r = await nc.request("POST", f"/projects/{params.project_id}/documents", files={"file": (params.filename, params.text.encode("utf-8"), "text/plain")})
            return f"Uploaded document {r['id']}" + (" (identical file already existed)" if r.get("duplicate") else "") + f". Next: noesis_analyze_document(project_id={params.project_id}, document_id={r['id']})."
        return await guarded(go())

    @mcp.tool(name="noesis_analyze_document", annotations=WRITE)
    async def noesis_analyze_document(params: AnalyzeIn) -> str:
        """Start the full analysis of an uploaded paper (claims, statistics checks, evidence, beliefs, hypotheses, report). Returns a job id; poll with noesis_wait_for_job."""
        async def go():
            r = await nc.request("POST", f"/projects/{params.project_id}/documents/{params.document_id}/analyze")
            return f"Started job {r['job_id']}. Use noesis_wait_for_job(job_id={r['job_id']})."
        return await guarded(go())

    @mcp.tool(name="noesis_ask_question", annotations=WRITE)
    async def noesis_ask_question(params: AskIn) -> str:
        """Investigate a research question: propose testable hypotheses, retrieve and grade evidence, apply the veracity gate, and write a report. Returns a job id; poll with noesis_wait_for_job."""
        async def go():
            r = await nc.request("POST", f"/projects/{params.project_id}/query", json={"question": params.question})
            return f"Started job {r['job_id']}. Use noesis_wait_for_job(job_id={r['job_id']}), then noesis_get_report(project_id={params.project_id})."
        return await guarded(go())

    def _job_text(j: dict) -> str:
        res = j.get("result") or {}
        out = [f"Job {j['id']}: **{j['status']}**"]
        if j.get("error"):
            out.append(f"error: {j['error']}")
        if res.get("coverage"):
            out.append("Coverage:")
            out += [f"- {c['hypothesis']}: {c['status']} (independent sources {c['n_effective']}, veracity gate {'passed' if c['gate']['passed'] else 'WITHHELD'})" for c in res["coverage"]]
        if res.get("tasks"):
            out.append("Tasks: " + ", ".join(f"{k}={v['status']}" for k, v in res["tasks"].items()))
        if j["status"] in TERMINAL and j["status"] != "failed":
            out.append("Next: noesis_get_report, noesis_get_beliefs, noesis_list_hypotheses.")
        return "\n".join(out)

    @mcp.tool(name="noesis_get_job", annotations=RO)
    async def noesis_get_job(params: JobIn) -> str:
        """Get the current state of a job (queued/running/completed/failed) with its result summary."""
        return await guarded(_get_job(nc, params.job_id))

    async def _get_job(c, jid):
        return _job_text(await c.request("GET", f"/jobs/{jid}"))

    @mcp.tool(name="noesis_wait_for_job", annotations=RO)
    async def noesis_wait_for_job(params: WaitIn) -> str:
        """Wait (up to timeout_seconds) for a job to finish and return its state. If still running, call again; the job is not cancelled."""
        async def go():
            for _ in range(params.timeout_seconds):
                j = await nc.request("GET", f"/jobs/{params.job_id}")
                if j["status"] in TERMINAL:
                    return _job_text(j)
                await asyncio.sleep(1)
            return _job_text(j) + f"\nStill running after {params.timeout_seconds}s; call noesis_wait_for_job again."
        return await guarded(go())

    # ---------------- reading results ----------------
    @mcp.tool(name="noesis_get_claims", annotations=RO)
    async def noesis_get_claims(params: ClaimsIn) -> str:
        """List claims extracted from a project's documents, each with page and section (source location)."""
        async def go():
            cs = [c for c in await nc.request("GET", f"/projects/{params.project_id}/claims") if not params.kind or c["kind"] == params.kind]
            pg = _page(cs, params)
            if params.response_format == Fmt.json:
                return _clip(_j(pg))
            body = "\n".join(f"- [{c['id']}] p.{c['page']} {c['section']} · {c['kind']}: {c['text'][:300]}" for c in pg["items"]) or "No claims."
            return _clip(f"{pg['total']} claims (showing {pg['count']} from offset {pg['offset']}; has_more={pg['has_more']}, next_offset={pg['next_offset']})\n{body}")
        return await guarded(go())

    @mcp.tool(name="noesis_get_beliefs", annotations=RO)
    async def noesis_get_beliefs(params: BeliefsIn) -> str:
        """List evidence-graded beliefs: each claim with its independent supporting/contradicting sources, grade criteria and flags (e.g. inconsistent statistics)."""
        async def go():
            bs = [b for b in await nc.request("GET", f"/projects/{params.project_id}/beliefs") if not params.assessment or b["assessment"] == params.assessment]
            pg = _page(bs, params)
            if params.response_format == Fmt.json:
                return _clip(_j(pg))
            head = f"{pg['total']} beliefs (showing {pg['count']} from offset {pg['offset']}; has_more={pg['has_more']}, next_offset={pg['next_offset']})\n\n"
            return _clip(head + "\n\n".join(_md_belief(b) for b in pg["items"]) if pg["items"] else "No beliefs. Run noesis_ask_question or noesis_analyze_document first.")
        return await guarded(go())

    @mcp.tool(name="noesis_get_belief_history", annotations=RO)
    async def noesis_get_belief_history(params: BeliefRef) -> str:
        """Full audit trail of a belief: every version, action and reason."""
        async def go():
            h = await nc.request("GET", f"/beliefs/{params.belief_id}/history")
            return "\n".join(f"- v{x['version']} {x['action']} ({x['at']}): {x['reason']} → {x['snapshot'].get('assessment')}" for x in h)
        return await guarded(go())

    @mcp.tool(name="noesis_submit_belief_feedback", annotations=WRITE)
    async def noesis_submit_belief_feedback(params: FeedbackIn) -> str:
        """Human-in-the-loop: dispute or invalidate a belief, or restore an earlier version. Fully audited and reversible via restore."""
        async def go():
            body = {"action": params.action, "reason": params.reason, "version": params.version}
            r = await nc.request("POST", f"/beliefs/{params.belief_id}/feedback", json=body)
            return f"Belief {r['id']} is now status={r['status']}, assessment={r['assessment']}, version {r['version']}."
        return await guarded(go())

    @mcp.tool(name="noesis_list_hypotheses", annotations=RO)
    async def noesis_list_hypotheses(params: HypIn) -> str:
        """List generated hypotheses (all unverified) with novelty check, verification status and proposed experiments."""
        async def go():
            hs = [h for h in await nc.request("GET", f"/projects/{params.project_id}/hypotheses") if not params.status or h["status"] == params.status]
            pg = _page(hs, params)
            if params.response_format == Fmt.json:
                return _clip(_j(pg))
            out = []
            for h in pg["items"]:
                e = h.get("proposed_experiment") or {}
                out.append(f"### {h['hypothesis_id']} [{h['status']}] {h['statement']}\n- method: {h['generation_method']} · gap: {h['scientific_gap']}\n"
                           f"- novelty: {h['novelty_assessment']['verdict']} (corpus {h['novelty_assessment']['corpus_size']}, {h['novelty_assessment']['search_date']}) · confidence: not assigned"
                           + (f"\n- experiment (proposal, not run): {e['design']}; n/group≈{e['sample_size']['n_per_group']} at assumed d={e['sample_size']['assumed_effect_size_d']}" if e else ""))
            return _clip(f"{pg['total']} hypotheses (has_more={pg['has_more']}, next_offset={pg['next_offset']})\n\n" + "\n\n".join(out) if out else "No hypotheses.")
        return await guarded(go())

    @mcp.tool(name="noesis_get_report", annotations=RO)
    async def noesis_get_report(params: ReportIn) -> str:
        """Get the latest report for a project (markdown with coverage matrix, evidence, gaps, experiments, limitations)."""
        async def go():
            r = await nc.request("GET", f"/projects/{params.project_id}/report")
            md = r["markdown"]
            return md if len(md) <= params.max_chars else md[:params.max_chars] + f"\n\n[truncated at {params.max_chars} characters; raise max_chars (max {CHARACTER_LIMIT})]"
        return await guarded(go())

    # ---------------- corpus ----------------
    @mcp.tool(name="noesis_search_corpus", annotations=RO)
    async def noesis_search_corpus(params: SearchIn) -> str:
        """Search the locally harvested literature corpus (hybrid keyword + latent-semantic retrieval). Retracted papers are excluded."""
        async def go():
            need = min(params.offset + params.limit, 50)
            from urllib.parse import quote
            items = await nc.request("GET", f"/corpus/search?q={quote(params.query)}&k={need}")
            pg = _page(items, params)
            if params.response_format == Fmt.json:
                return _clip(_j(pg))
            body = "\n".join(f"- {p['score']:.2f} · {p['title'][:110]} ({p['year']}, {p['source']}, {p['design']}) doi:{p['doi'] or 'n/a'} license:{p['license'] or 'unknown'}" for p in pg["items"])
            return body or "No matches. The corpus may be empty: harvest with noesis_start_corpus_harvest or `python -m noesis.cli sync`."
        return await guarded(go())

    @mcp.tool(name="noesis_corpus_stats", annotations=RO)
    async def noesis_corpus_stats() -> str:
        """Size and composition of the literature corpus (by source, domain, study design; retracted count)."""
        return await guarded(_corpus_stats(nc))

    async def _corpus_stats(c):
        return _j(await c.request("GET", "/corpus/stats"))

    @mcp.tool(name="noesis_start_corpus_harvest", annotations=EXTERNAL)
    async def noesis_start_corpus_harvest(params: HarvestIn) -> str:
        """Harvest real papers from public scholarly APIs into the shared corpus (admin when accounts are enabled). Runs in the background; check noesis_corpus_stats."""
        async def go():
            r = await nc.request("POST", "/corpus/sync", json=params.model_dump())
            return f"Harvest {r['status']} for topics {r['topics']}. Check progress with noesis_corpus_stats."
        return await guarded(go())

    # ---------------- exact engines (no project needed) ----------------
    async def engine(name: str, p: dict) -> dict:
        return await nc.request("POST", f"/engines/{name}/run", json={"params": p})

    @mcp.tool(name="noesis_list_engines", annotations=RO)
    async def noesis_list_engines() -> str:
        """List the reasoning engines and their capabilities."""
        async def go():
            return "\n".join(f"- {k}: {', '.join(v['capabilities'])}" for k, v in (await nc.request("GET", "/engines")).items())
        return await guarded(go())

    @mcp.tool(name="noesis_check_reported_statistics", annotations=COMPUTE)
    async def noesis_check_reported_statistics(params: StatsIn) -> str:
        """Recompute p-values from reported test statistics (t, F, chi2, r) accounting for rounding, and flag inconsistent or decision-changing results."""
        async def go():
            return _j(await engine("statistical_engine", {"operation": "check_reports", "reports": [r.model_dump(exclude_none=True) for r in params.reports]}))
        return await guarded(go())

    @mcp.tool(name="noesis_meta_analysis", annotations=COMPUTE)
    async def noesis_meta_analysis(params: MetaIn) -> str:
        """Inverse-variance meta-analysis: pooled effect, 95% CI, heterogeneity (Q, I², tau²)."""
        async def go():
            return _j(await engine("statistical_engine", {"operation": "meta_analysis", "effects": params.effects, "ses": params.standard_errors, "model": params.model}))
        return await guarded(go())

    @mcp.tool(name="noesis_sample_size", annotations=COMPUTE)
    async def noesis_sample_size(params: SampleIn) -> str:
        """Participants per group needed for a two-sample t-test at a given effect size, alpha and power (exact noncentral-t)."""
        async def go():
            return _j(await engine("statistical_engine", {"operation": "sample_size", "d": params.effect_size_d, "alpha": params.alpha, "power": params.power}))
        return await guarded(go())

    @mcp.tool(name="noesis_check_grim", annotations=COMPUTE)
    async def noesis_check_grim(params: GrimIn) -> str:
        """GRIM test: can a mean reported to this precision arise from n integer-valued observations? (detects impossible reported means)"""
        async def go():
            return _j(await engine("statistical_engine", {"operation": "grim", "mean": params.mean, "n": params.n}))
        return await guarded(go())

    @mcp.tool(name="noesis_check_dimensions", annotations=COMPUTE)
    async def noesis_check_dimensions(params: DimsIn) -> str:
        """Check an equation for SI dimensional consistency (both sides equal dimensions, sums homogeneous, transcendental arguments dimensionless)."""
        async def go():
            return _j(await engine("math_engine", {"operation": "check_dimensions", "lhs": params.lhs, "rhs": params.rhs, "units": params.units}))
        return await guarded(go())

    @mcp.tool(name="noesis_check_equation_identity", annotations=COMPUTE)
    async def noesis_check_equation_identity(params: EqIn) -> str:
        """Check whether lhs == rhs is an algebraic identity (symbolic, with numeric confirmation). A relation that holds only for some values is reported as not_identity, which is not necessarily an error."""
        async def go():
            return _j(await engine("math_engine", {"operation": "check_equations", "equations": [f"{params.lhs} = {params.rhs}"]}))
        return await guarded(go())

    @mcp.tool(name="noesis_simulate_orbit", annotations=COMPUTE)
    async def noesis_simulate_orbit(params: OrbitIn) -> str:
        """Propagate a Newtonian two-body orbit around Earth (point mass, no drag/J2). Returns conservation checks, Kepler period and final state, with assumptions."""
        async def go():
            r = await engine("simulation_engine", {"operation": "two_body", "r0": params.position_m, "v0": params.velocity_mps, "t_end": params.duration_s, "n_points": 50})
            return _j(r)
        return await guarded(go())

    return mcp
