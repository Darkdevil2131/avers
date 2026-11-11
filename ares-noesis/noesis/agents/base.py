"""Structured agent protocol. Agents exchange TaskMessage/TaskResult, never free-form chat."""
import re
import time

from pydantic import BaseModel, Field

from ..connectors.base import ConnectorError, ConnectorUnavailable


class TaskMessage(BaseModel):
    task_id: str
    agent: str
    objective: str
    inputs: dict = Field(default_factory=dict)
    required_operations: list[str] = Field(default_factory=list)
    status: str = "pending"


class TaskResult(BaseModel):
    task_id: str
    agent: str
    status: str  # completed | partial | failed | unavailable | permission_denied
    outputs: dict = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)
    log: list[dict] = Field(default_factory=list)
    duration_s: float = 0.0


DESIGN_RULES = {  # shared design vocabulary; each agent adds its own
    "meta_analysis": r"\bmeta-?analy", "systematic_review": r"\bsystematic review",
    "rct": r"\brandomi[sz]ed\b.*\b(trial|controlled)|\brandomi[sz]ed controlled",
    "cohort": r"\bcohort\b", "case_control": r"\bcase-control", "cross_sectional": r"\bcross-sectional",
    "case_report": r"\bcase report", "preclinical_animal": r"\b(mice|mouse|murine|rats?|in vivo)\b",
    "in_vitro": r"\bin vitro\b|\bcell lines?\b",
}


class DomainAgent:
    domain = "generic"
    connector_names: list[str] = []
    design_rules: dict = {}
    operations = {"literature_search"}
    allowed_engines: list[str] = []

    def __init__(self, connectors: dict):
        self.connectors = {n: connectors[n] for n in self.connector_names if n in connectors}
        self.connectors_all = connectors
        self.working_memory: dict = {}
        self.log: list = []

    def classify(self, paper) -> str:
        text = f"{paper.title} {paper.abstract}".lower()
        for t in paper.pub_types:
            tl = t.lower()
            if "randomized controlled trial" in tl:
                return "rct"
            if "meta-analysis" in tl:
                return "meta_analysis"
            if "systematic review" in tl:
                return "systematic_review"
        rules = {**DESIGN_RULES, **self.design_rules}
        for design, rx in rules.items():
            if re.search(rx, text):
                return design
        return "unknown"

    def execute(self, msg: TaskMessage) -> TaskResult:
        t0 = time.time()
        res = TaskResult(task_id=msg.task_id, agent=msg.agent, status="completed")
        for op in msg.required_operations:
            if op not in self.operations:
                res.status = "permission_denied"
                res.errors.append({"operation": op, "error": "operation outside this agent's permission boundary"})
                continue
            getattr(self, f"op_{op}")(msg, res)
        res.duration_s = round(time.time() - t0, 4)
        self.log.append({"task": msg.task_id, "status": res.status, "duration_s": res.duration_s})
        return res

    def op_literature_search(self, msg: TaskMessage, res: TaskResult):
        queries = msg.inputs.get("queries", [])
        limit = int(msg.inputs.get("limit", 5))
        budget = int(msg.inputs.get("budget", 20))
        papers, per_conn = [], {}
        used = 0
        for cname, conn in self.connectors.items():
            per_conn[cname] = {"status": "ok", "n": 0}
            for q in queries:
                if used >= budget:
                    per_conn[cname]["status"] = "budget_exhausted"
                    break
                used += 1
                try:
                    found = conn.search(q, limit)
                except ConnectorUnavailable as e:
                    per_conn[cname] = {"status": "unavailable", "reason": e.reason, "n": per_conn[cname]["n"]}
                    res.errors.append({"connector": cname, "error": "unavailable", "reason": e.reason})
                    break
                except ConnectorError as e:
                    per_conn[cname] = {"status": "error", "reason": str(e), "n": per_conn[cname]["n"]}
                    res.errors.append({"connector": cname, "error": str(e)})
                    break
                for p in found:
                    d = p.model_dump()
                    d["design"] = self.classify(p)
                    d["domain"] = self.domain
                    d["content_hash"] = p.content_hash
                    papers.append(d)
                per_conn[cname]["n"] += len(found)
        seen, uniq = set(), []
        for p in papers:
            if p["content_hash"] not in seen:
                seen.add(p["content_hash"])
                uniq.append(p)
        res.outputs["papers"] = uniq
        res.outputs["connectors"] = per_conn
        if not uniq and res.errors:
            res.status = "unavailable"
        elif res.errors:
            res.status = "partial"
        res.limitations.append("design classification is keyword-based (unvalidated); treat as a lead, not a finding")
