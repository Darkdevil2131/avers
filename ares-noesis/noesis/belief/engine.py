"""Belief engine: auditable, versioned, dependency-aware evidence pooling.

Method (log-odds pooling v1):
  prior odds = 1 (uninformative).  Each *independence group* contributes at most ONE item (its strongest),
  so papers sharing a dataset/research group are not counted as independent evidence.
  contribution = +/- ln(LR[grade]).   LR table is an ASSUMPTION (not calibrated): see docs/BELIEF.md.
  Self-reported evidence from the source document contributes nothing (LR=1).
Output `calibrated: false` is carried everywhere; do not present the posterior as a probability of truth.
"""
import math
from dataclasses import asdict

from sqlalchemy import select

from ..models import Belief, BeliefEvent, EvidenceItem, now
from ..verification.evidence import SELF_GROUP, EvidenceInput, assess, classify_support

LR = {1: 1.2, 2: 1.8, 3: 3.0, 4: 5.0}


def pool(items: list) -> dict:
    best = {}
    for i in items:
        if i["grade"] <= 0 or i["stance"] not in ("supports", "contradicts") or i["group"] == SELF_GROUP:
            continue
        k = i["group"] or f"unique:{id(i)}"
        if k not in best or i["grade"] > best[k]["grade"]:
            best[k] = i
    logodds = sum((1 if i["stance"] == "supports" else -1) * math.log(LR[i["grade"]]) for i in best.values())
    sup = [i for i in best.values() if i["stance"] == "supports"]
    con = [i for i in best.values() if i["stance"] == "contradicts"]
    n_eff = len(best)
    post = 1 / (1 + math.exp(-logodds)) if n_eff else None
    if not n_eff:
        label, unc = "insufficient_evidence", "high"
    else:
        strong_s, strong_c = [i for i in sup if i["grade"] >= 2], [i for i in con if i["grade"] >= 2]
        if strong_s and strong_c:
            label = "disputed"
        elif post >= 0.8 and not strong_c and n_eff >= 2:
            label = "supported"
        elif post >= 0.6:
            label = "conditionally_supported"
        elif post <= 0.25:
            label = "contradicted"
        else:
            label = "inconclusive"
        unc = "low" if n_eff >= 3 and not con else ("high" if n_eff <= 1 else "moderate")
    return {"posterior": round(post, 4) if post is not None else None, "n_effective": n_eff, "assessment": label,
            "uncertainty": unc, "calibrated": False, "method": "log-odds pooling v1 (LR table assumed)"}


class BeliefEngine:
    def __init__(self, session):
        self.s = session

    # --- helpers
    def _items(self, belief_id: int, only_active=True) -> list:
        q = select(EvidenceItem).where(EvidenceItem.belief_id == belief_id)
        if only_active:
            q = q.where(EvidenceItem.active.is_(True))
        return list(self.s.scalars(q))

    @staticmethod
    def _as_dict(e: EvidenceItem) -> dict:
        return {"id": e.id, "stance": e.stance, "grade": e.grade, "group": e.independence_group}

    def _event(self, b: Belief, action: str, reason: str):
        ids = [e.id for e in self._items(b.id)]
        snap = {"posterior": b.posterior, "assessment": b.assessment, "status": b.status, "support_class": b.support_class,
                "evidence_ids": ids, "assumptions": list(b.assumptions or []), "flags": list(b.flags or [])}
        self.s.add(BeliefEvent(belief_id=b.id, version=b.version, action=action, reason=reason, snapshot=snap))

    def recompute(self, b: Belief, action: str, reason: str) -> Belief:
        items = [self._as_dict(e) for e in self._items(b.id)]
        p = pool(items)
        b.posterior, b.n_effective, b.uncertainty = p["posterior"], p["n_effective"], p["uncertainty"]
        b.assessment = p["assessment"]
        b.support_class = classify_support(items)
        b.version += 1
        b.updated_at = now()
        self.s.flush()
        self._event(b, action, reason)
        self.s.flush()
        return b

    # --- public API (create / update / merge / split / dispute / invalidate / restore)
    def create(self, project_id: int, claim_text: str, assumptions=None, claim_id=None, reason="created") -> Belief:
        b = Belief(project_id=project_id, claim_text=claim_text, claim_id=claim_id, assumptions=list(assumptions or []))
        self.s.add(b)
        self.s.flush()
        return self.recompute(b, "create", reason)

    def add_evidence(self, belief_id: int, ev: EvidenceInput, reason: str) -> EvidenceItem:
        b = self.s.get(Belief, belief_id)
        a = assess(ev)
        item = EvidenceItem(
            belief_id=belief_id, paper_id=ev.paper_id, title=ev.title, source=ev.source, doi=ev.doi, design=ev.design,
            stance=ev.stance, sample_size=ev.sample_size, peer_reviewed=ev.peer_reviewed, retracted=ev.retracted,
            independence_group=ev.independence_group, grade=a["grade"], grade_label=a["label"], criteria=a["criteria"],
            method="evidence_v1", provenance=ev.provenance)
        self.s.add(item)
        self.s.flush()
        self.recompute(b, "add_evidence", reason)
        return item

    def relabel_groups(self, belief_id: int, mapping: dict, reason: str):
        """Update independence groups by paper id (used when later retrieval rounds reveal shared authorship). One new version if anything changed."""
        changed = False
        for e in self._items(belief_id):
            g = mapping.get(e.paper_id)
            if g and g != e.independence_group:
                e.independence_group, changed = g, True
        if changed:
            self.recompute(self.s.get(Belief, belief_id), "relabel_lineage", reason)

    def add_flag(self, belief_id: int, flag: str, reason: str):
        b = self.s.get(Belief, belief_id)
        b.flags = list(b.flags or []) + [flag]
        self.recompute(b, "flag", reason)

    def mark_disputed(self, belief_id: int, reason: str):
        b = self.s.get(Belief, belief_id)
        b.status = "disputed"
        return self.recompute(b, "mark_disputed", reason)

    def invalidate(self, belief_id: int, reason: str):
        b = self.s.get(Belief, belief_id)
        b.status = "invalidated"
        return self.recompute(b, "invalidate", reason)

    def merge(self, target_id: int, source_id: int, reason: str):
        t, s_ = self.s.get(Belief, target_id), self.s.get(Belief, source_id)
        for e in self._items(source_id):
            e.belief_id = target_id
        s_.status = "merged"
        t.assumptions = sorted(set((t.assumptions or []) + (s_.assumptions or [])))
        self.recompute(s_, "merged_into", f"merged into belief {target_id}: {reason}")
        return self.recompute(t, "merge", f"absorbed belief {source_id}: {reason}")

    def split(self, belief_id: int, evidence_ids: list, new_claim_text: str, reason: str) -> Belief:
        b = self.s.get(Belief, belief_id)
        nb = self.create(b.project_id, new_claim_text, assumptions=b.assumptions, reason=f"split from {belief_id}")
        for e in self._items(belief_id):
            if e.id in evidence_ids:
                e.belief_id = nb.id
        self.recompute(nb, "split_in", reason)
        self.recompute(b, "split_out", reason)
        return nb

    def history(self, belief_id: int) -> list:
        q = select(BeliefEvent).where(BeliefEvent.belief_id == belief_id).order_by(BeliefEvent.id)
        return [{"version": e.version, "action": e.action, "reason": e.reason, "snapshot": e.snapshot,
                 "at": e.created_at.isoformat()} for e in self.s.scalars(q)]

    def restore(self, belief_id: int, version: int, reason: str = "") -> Belief:
        """Restore evidence membership/assumptions/flags/status of a historical version as a NEW version (history is append-only)."""
        q = select(BeliefEvent).where(BeliefEvent.belief_id == belief_id, BeliefEvent.version == version)
        ev = self.s.scalars(q).first()
        if ev is None:
            raise ValueError(f"belief {belief_id} has no version {version}")
        snap = ev.snapshot
        moved = [e.id for e in self.s.scalars(select(EvidenceItem).where(EvidenceItem.id.in_(snap["evidence_ids"] or [0]), EvidenceItem.belief_id != belief_id))]
        if moved:
            raise ValueError(f"cannot restore version {version}: evidence {moved} was moved to another belief by a split/merge; undo that first")
        for e in self._items(belief_id, only_active=False):
            e.active = e.id in snap["evidence_ids"]
        b = self.s.get(Belief, belief_id)
        b.assumptions, b.flags, b.status = list(snap["assumptions"]), list(snap["flags"]), snap["status"]
        return self.recompute(b, "restore", f"restored version {version}. {reason}".strip())
