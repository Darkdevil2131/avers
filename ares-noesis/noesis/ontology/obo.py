"""Ontology loading (OBO format) and concept matching.

OBO is the exchange format of many open ontologies (Gene Ontology, ChEBI, Disease Ontology, ...). Load a real file you have the right to use;
nothing is bundled and nothing is seeded. Matching is exact on normalised labels/synonyms (n-grams up to 5 words), so it never guesses:
a phrase either is a known term or synonym or it is not."""
import re

from sqlalchemy import select

from ..models import Concept

_Q = re.compile(r'^"((?:[^"\\]|\\.)*)"')


def parse_obo(text: str) -> list:
    terms, cur = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            if cur is not None:
                terms.append(cur)
            cur = {"id": "", "name": "", "def": "", "synonyms": [], "is_a": [], "obsolete": False} if line == "[Term]" else None
            continue
        if cur is None or ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip()
        if key == "id":
            cur["id"] = val
        elif key == "name":
            cur["name"] = val
        elif key == "def":
            m = _Q.match(val)
            cur["def"] = m.group(1) if m else val
        elif key == "synonym":
            m = _Q.match(val)
            if m:
                cur["synonyms"].append(m.group(1))
        elif key == "is_a":
            cur["is_a"].append(val.split("!")[0].strip())
        elif key == "is_obsolete":
            cur["obsolete"] = val.lower() == "true"
    if cur is not None:
        terms.append(cur)
    return [t for t in terms if t["id"] and t["name"]]


def load_obo(s, text: str, ontology: str) -> dict:
    """Insert new terms, update existing ones (idempotent per (ontology, term id)). Returns counts."""
    new = upd = 0
    for t in parse_obo(text):
        row = s.scalars(select(Concept).where(Concept.ontology == ontology, Concept.term_id == t["id"])).first()
        if row is None:
            s.add(Concept(ontology=ontology, term_id=t["id"], label=t["name"], definition=t["def"], synonyms=t["synonyms"], parents=t["is_a"], obsolete=t["obsolete"]))
            new += 1
        else:
            row.label, row.definition, row.synonyms, row.parents, row.obsolete = t["name"], t["def"], t["synonyms"], t["is_a"], t["obsolete"]
            upd += 1
    s.flush()
    _INDEX.clear()
    return {"ontology": ontology, "new": new, "updated": upd}


_INDEX: dict = {}


def _norm(x: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\- ]", " ", x.lower())).strip()


def _index(s):
    key = (id(s.get_bind()), s.scalar(select(__import__("sqlalchemy").func.count(Concept.id))))
    if key in _INDEX:
        return _INDEX[key]
    idx = {}
    for c in s.scalars(select(Concept).where(Concept.obsolete.is_(False))):
        for name in [c.label, *(c.synonyms or [])]:
            n = _norm(name)
            if len(n) >= 3:
                idx.setdefault(n, []).append(c)
    _INDEX.clear()
    _INDEX[key] = idx
    return idx


def annotate(s, text: str, max_words: int = 5) -> list:
    """Known ontology terms mentioned in text: [{mention, ontology, term_id, label, synonyms}], longest match first, non-overlapping."""
    idx = _index(s)
    if not idx:
        return []
    words = _norm(text).split()
    out, i = [], 0
    while i < len(words):
        for n in range(min(max_words, len(words) - i), 0, -1):
            phrase = " ".join(words[i:i + n])
            if phrase in idx:
                c = idx[phrase][0]
                out.append({"mention": phrase, "ontology": c.ontology, "term_id": c.term_id, "label": c.label, "synonyms": list(c.synonyms or [])[:10]})
                i += n
                break
        else:
            i += 1
    return out
