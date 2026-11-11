import json
from typing import Literal

from pydantic import BaseModel, Field
class Fingerprint(BaseModel):
    subject: str = Field(default="", max_length=300)
    variable: str = Field(default="", max_length=300)
    units: str = Field(default="", max_length=100)
    population_or_material: str = Field(default="", max_length=500)
    conditions: str = Field(default="", max_length=1000)
    study_design: str = Field(default="", max_length=300)
    outcome: str = Field(default="", max_length=500)
    measurement: str = Field(default="", max_length=300)
    timeframe: str = Field(default="", max_length=300)
class ClaimInput(BaseModel):
    statement: str = Field(min_length=8, max_length=2000)
    fingerprint: Fingerprint
class EvidenceInput(BaseModel):
    source_id: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    stance: Literal["supports", "contradicts", "neutral"]
    fingerprint: Fingerprint
    rationale: str = Field(min_length=8, max_length=2000)
class HypothesisInput(BaseModel):
    statement: str = Field(min_length=8, max_length=2000)
    mechanism: str = Field(min_length=8, max_length=3000)
    falsification: str = Field(min_length=8, max_length=3000)
    predecessor: str | None = None
def compare_context(left, right):
    mismatches, missing = [], []
    for field in Fingerprint.model_fields:
        first, second = left.get(field, "").strip().casefold(), right.get(field, "").strip().casefold()
        if not first or not second:
            missing.append(field)
        elif first != second:
            mismatches.append(field)
    if mismatches:
        return {"state": "context-mismatched", "fields": mismatches}
    if missing:
        return {"state": "unverified", "fields": missing}
    return {"state": "compatible", "fields": []}
def assess(db, claim):
    fingerprint = json.loads(claim["fingerprint"])
    rows = db.execute("""
        SELECT e.*,coalesce(d.study_id,s.url) AS study_id,s.url,
        coalesce((SELECT status FROM source_reviews WHERE source_id=e.source_id ORDER BY id DESC LIMIT 1),'active') AS source_status
        FROM evidence_links e JOIN sources s ON s.id=e.source_id
        LEFT JOIN source_details d ON d.source_id=e.source_id WHERE e.claim_id=? ORDER BY e.created_at,e.id
    """, (claim["id"],)).fetchall()
    evidence, stances, groups = [], set(), set()
    for row in rows:
        item = dict(row)
        item["fingerprint"] = json.loads(item["fingerprint"])
        item["context"] = compare_context(fingerprint, item["fingerprint"])
        if item["source_status"] == "active" and item["context"]["state"] == "compatible":
            stances.add(item["stance"])
            groups.add(item["study_id"])
        evidence.append(item)
    status = "inconclusive"
    if {"supports", "contradicts"} <= stances:
        status = "mixed"
    elif "contradicts" in stances:
        status = "contradicted"
    elif "supports" in stances:
        status = "supported"
    elif evidence and all(item["source_status"] == "retracted" for item in evidence):
        status = "retracted-source"
    elif any(item["context"]["state"] == "context-mismatched" for item in evidence):
        status = "context-mismatched"
    elif evidence:
        status = "unverified"
    return {**dict(claim), "fingerprint": fingerprint, "assessment": status,
            "basis": "reviewer-entered evidence relationships", "calibrated": False,
            "confidence": None, "study_groups": len(groups), "independence_verified": False,
            "evidence": evidence}
