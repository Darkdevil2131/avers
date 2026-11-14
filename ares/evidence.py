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
        first, second = left.get(field, "").strip(), right.get(field, "").strip()
        # Unit symbols are case-sensitive: MPa and mPa differ by nine orders of magnitude.
        if field != "units":
            first, second = first.casefold(), second.casefold()
        if not first or not second:
            missing.append(field)
        elif first != second:
            mismatches.append(field)
    if mismatches:
        return {"state": "context-mismatched", "fields": mismatches}
    if missing:
        return {"state": "unverified", "fields": missing}
    return {"state": "compatible", "fields": []}


def reviewed_finding_contexts(db, project_id, findings):
    """Load bounded reviewer records for the exact, currently active finding spans."""
    contexts = {}
    for finding in findings:
        rows = db.execute("""
            SELECT e.id, e.claim_id, e.fingerprint
            FROM evidence_links e
            JOIN claims c ON c.id=e.claim_id
            JOIN sources s ON s.id=e.source_id AND s.project_id=c.project_id
            WHERE c.project_id=? AND e.source_id=? AND e.start_offset=? AND e.end_offset=?
              AND e.quote=?
              AND coalesce((SELECT status FROM source_reviews WHERE source_id=s.id
                            ORDER BY id DESC LIMIT 1), 'active')='active'
            ORDER BY e.id LIMIT 65
        """, (project_id, finding['source_id'], finding['start_offset'],
              finding['end_offset'], finding['statement'])).fetchall()
        key = finding['source_id'], finding['start_offset'], finding['end_offset']
        contexts[key] = None if len(rows) > 64 else [
            {'id': row['id'], 'claim_id': row['claim_id'], 'fingerprint': json.loads(row['fingerprint'])}
            for row in rows
        ]
    return contexts


def compare_reviewed_findings(left, right, contexts):
    """Compare human-entered fields only where both records reference a common claim."""
    def records(finding):
        key = finding['source_id'], finding.get('start_offset'), finding.get('end_offset')
        return contexts.get(key, [])

    left_records, right_records = records(left), records(right)
    result = {'state': 'unverified', 'fields': [], 'review_ids': [], 'claim_ids': []}
    if left_records is None or right_records is None:
        return {**result, 'reason': 'Review record limit exceeded for an exact finding span.'}

    right_by_claim = {}
    for record in right_records:
        right_by_claim.setdefault(record['claim_id'], []).append(record)
    comparisons, review_ids, claim_ids = set(), set(), set()
    for first in left_records:
        for second in right_by_claim.get(first['claim_id'], []):
            comparison = compare_context(first['fingerprint'], second['fingerprint'])
            comparisons.add((comparison['state'], tuple(comparison['fields'])))
            review_ids.update((first['id'], second['id']))
            claim_ids.add(first['claim_id'])
    if not comparisons:
        return {**result, 'reason': 'No exact-span reviews link both findings to a shared claim.'}

    result.update(review_ids=sorted(review_ids), claim_ids=sorted(claim_ids))
    if len(comparisons) != 1:
        return {**result, 'state': 'review-conflict', 'reason': 'Reviewer records yield different context comparisons.'}
    state, fields = comparisons.pop()
    return {**result, 'state': state, 'fields': list(fields),
            'reason': 'Comparison of reviewer-entered fields on exact spans linked to the same claim.'}
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
