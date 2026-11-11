"""Transparent evidence-quality framework (GRADE-inspired, adapted for tech/space; NOT validated).

No truth score is derived from journal prestige or citation counts - those are stored as metadata only.
Every grade comes with the list of criteria that produced it.
"""
import re
from dataclasses import dataclass, field

BASE_GRADE = {
    "systematic_review": 4, "meta_analysis": 4, "rct": 4,
    "benchmark": 3, "observational_astronomy": 3, "observational": 3,
    "cohort": 2, "case_control": 2, "cross_sectional": 2, "preclinical_animal": 2, "simulation": 2, "theoretical": 2,
    "review": 2, "case_report": 1, "in_vitro": 1, "expert_opinion": 1, "unknown": 1, "self_reported": 1,
}
SAMPLE_BASED = {"rct", "cohort", "case_control", "cross_sectional", "preclinical_animal", "case_report"}
LABELS = {0: "excluded", 1: "very_low", 2: "low", 3: "moderate", 4: "high"}
SELF_GROUP = "source_document"


@dataclass
class EvidenceInput:
    title: str = ""
    source: str = ""
    doi: str = ""
    design: str = "unknown"
    stance: str = "neutral"  # supports | contradicts | neutral
    sample_size: int | None = None
    peer_reviewed: bool | None = None
    retracted: bool = False
    independent_replication: bool = False
    independence_group: str = ""
    provenance: dict = field(default_factory=dict)
    paper_id: int | None = None


def assess(ev: EvidenceInput) -> dict:
    criteria = []
    if ev.retracted:
        return {"grade": 0, "label": "excluded", "criteria": [{"criterion": "retraction", "effect": "excluded", "reason": "source is retracted"}]}
    design = ev.design if ev.design in BASE_GRADE else "unknown"
    grade = BASE_GRADE[design]
    criteria.append({"criterion": "study_design", "effect": f"start at {grade}", "reason": design})
    if ev.peer_reviewed is False:
        grade -= 1
        criteria.append({"criterion": "publication_status", "effect": "-1", "reason": "not peer reviewed (preprint)"})
    elif ev.peer_reviewed is None:
        criteria.append({"criterion": "publication_status", "effect": "0", "reason": "not assessed"})
    if design in SAMPLE_BASED:
        if ev.sample_size is not None and ev.sample_size < 30:
            grade -= 1
            criteria.append({"criterion": "sample_size", "effect": "-1", "reason": f"n={ev.sample_size} < 30"})
        elif ev.sample_size is None:
            criteria.append({"criterion": "sample_size", "effect": "0", "reason": "not reported/not extracted"})
    if ev.independent_replication:
        grade += 1
        criteria.append({"criterion": "independent_replication", "effect": "+1", "reason": "replicated by an independent group"})
    grade = max(1, min(4, grade))
    return {"grade": grade, "label": LABELS[grade], "criteria": criteria}


def infer_design_from_text(text: str) -> str:
    t = text.lower()
    for d, rx in [("meta_analysis", r"meta-?analy"), ("systematic_review", r"systematic review"),
                  ("rct", r"randomi[sz]ed"), ("cohort", r"\bcohort\b"), ("preclinical_animal", r"\b(mice|rats?|murine|in vivo)\b"),
                  ("benchmark", r"benchmark"), ("simulation", r"simulat")]:
        if re.search(rx, t):
            return d
    return "unknown"


_STOP = set("the a an of and or in on for to with by from at as is are was were be this that these those it its we our their than then which using use used based can may not no".split())


def content_tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z][a-z\-]{2,}", text.lower()) if w not in _STOP}


def lexical_stance(claim: str, claim_triple: dict | None, passage: str, passage_triples: list) -> dict:
    """Heuristic stance. method is recorded; `validated: False` by design. Replace with NLI/LLM + calibration."""
    ct, pt = content_tokens(claim), content_tokens(passage)
    rel = len(ct & pt) / max(1, len(ct))
    out = {"relevance": round(rel, 3), "method": "lexical_overlap+triple_polarity_v1", "validated": False}
    if rel < 0.3:
        return {**out, "stance": "irrelevant"}
    if claim_triple:
        from ..ingestion.claims import triples_contradict
        for t in passage_triples:
            if t["subject"] == claim_triple["subject"] and t["object"] == claim_triple["object"]:
                if triples_contradict(claim_triple, t):
                    return {**out, "stance": "contradicts"}
                if t["relation"] == claim_triple["relation"] and t["negated"] == claim_triple["negated"]:
                    return {**out, "stance": "supports"}
    return {**out, "stance": "neutral"}


def classify_support(items: list) -> str:
    """items: dicts with stance, grade, group. Returns the support category for a claim."""
    ext = [i for i in items if i["grade"] > 0 and i["group"] != SELF_GROUP and i["stance"] in ("supports", "contradicts")]
    if not ext:
        return "not_independently_verifiable" if any(i["group"] == SELF_GROUP for i in items) else "unsupported"
    sup = [i["grade"] for i in ext if i["stance"] == "supports"]
    con = [i["grade"] for i in ext if i["stance"] == "contradicts"]
    if sup and not con:
        return "directly_supported" if max(sup) >= 3 else "partially_supported"
    if con and not sup:
        return "contradicted" if max(con) >= 2 else "inconclusive"
    if max(sup) > max(con):
        return "partially_supported"
    if max(con) > max(sup):
        return "contradicted"
    return "inconclusive"
