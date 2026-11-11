"""Rule-based claim / statistic / equation / triple extraction (heuristic, unvalidated).

Every output carries page + section + sentence text so it is traceable to the source.
Extraction method is recorded as `rule_v1`; swap in an LLM/NLI extractor behind the same shape.
"""
import re

FINDING_CUE = re.compile(
    r"\b(we (found|show|showed|demonstrate[d]?|observed|report|find)|results? (show|indicate|suggest|demonstrate)|"
    r"(significantly )?(increase[sd]?|decrease[sd]?|improve[sd]?|reduce[sd]?|outperform\w*|enhance[sd]?|"
    r"inhibit\w*|suppress\w*|lower\w*)|cause[sd]?|lead[s]? to|associated with|correlat\w+|linked to)\b",
    re.I,
)
LIMITATION_CUE = re.compile(r"\b(limitation|future work|we did not|could not|was not tested|not tested|beyond the scope)\b", re.I)
CAUSAL = re.compile(r"\b(cause[sd]?|causing|leads? to|led to|results? in|resulted in|drives?|induces?|due to|responsible for|mediates?)\b", re.I)
ASSOC = re.compile(r"\b(associated with|correlat\w+|linked to|related to)\b", re.I)

_P = r"(?P<op>[<=>])\s*(?P<p>\d*\.?\d+)"
STAT_PATTERNS = [
    ("t", re.compile(r"\bt\s*\(\s*(?P<df1>\d+(?:\.\d+)?)\s*\)\s*=\s*(?P<stat>-?\d*\.?\d+)\s*,?\s*p\s*" + _P, re.I)),
    ("F", re.compile(r"\bF\s*\(\s*(?P<df1>\d+)\s*,\s*(?P<df2>\d+)\s*\)\s*=\s*(?P<stat>\d*\.?\d+)\s*,?\s*p\s*" + _P)),
    ("chi2", re.compile(r"(?:χ2|χ²|chi-?square[d]?|chi2)\s*\(\s*(?P<df1>\d+)(?:\s*,\s*N\s*=\s*\d+)?\s*\)\s*=\s*(?P<stat>\d*\.?\d+)\s*,?\s*p\s*" + _P, re.I)),
    ("r", re.compile(r"\br\s*\(\s*(?P<df1>\d+)\s*\)\s*=\s*(?P<stat>-?\d*\.?\d+)\s*,?\s*p\s*" + _P)),
]

_POS = ("increas", "improv", "enhanc", "rais")
_NEG = ("decreas", "reduc", "lower", "inhibit", "suppress")
LEAD = re.compile(
    r"^(?:in this (?:study|work|paper),?\s*)?(?:we (?:found|show|showed|demonstrate[d]?|observed|report|find)|"
    r"(?:our )?results? (?:show|indicate|suggest|demonstrate))\s+(?:that\s+)?", re.I)
TRIPLE_RE = re.compile(
    r"(?P<s>[A-Za-z][\w\s\-/]{2,60}?)\s+(?:(?:significantly|substantially|markedly)\s+)?"
    r"(?P<neg>(?:does|do|did)\s+not\s+)?"
    r"(?P<v>increas\w+|improv\w+|enhanc\w+|rais\w+|decreas\w+|reduc\w+|lower\w*|inhibit\w*|suppress\w*)\s+"
    r"(?:the\s+)?(?P<o>[A-Za-z][\w\s\-/]{2,60}?)"
    r"(?=\s+(?:by|from|under|in|when|with|at|to|than|across|among|over|during|within|for|after|before|through|via|using|per|relative|compared|versus)\b|\s*[,.;:(]|$)",
    re.I,
)
_DET = re.compile(r"^(the|a|an|this|that|these|those|our|its)\s+", re.I)
_ADV = re.compile(r"\s+(significantly|substantially|markedly)$", re.I)

EQ_LINE = re.compile(
    r"^(?P<l>[A-Za-z\(][A-Za-z0-9_\s\(\)\^\*/\+\-\.]{0,40}?)\s*=\s*"
    r"(?P<r>[A-Za-z0-9_\s\(\)\^\*/\+\-\.]{1,60}?)\s*(?:\(\d+\))?$"
)


def _clean_entity(e: str) -> str:
    e = e.strip().lower()
    e = _DET.sub("", e)
    e = _ADV.sub("", e)
    return re.sub(r"\s+", " ", e).strip()


def extract_triple(sentence: str):
    s = LEAD.sub("", sentence.strip())
    m = TRIPLE_RE.search(s)
    if not m:
        return None
    verb = m.group("v").lower()
    if verb.startswith(_POS):
        rel = "increases"
    elif verb.startswith(_NEG):
        rel = "decreases"
    else:
        return None
    subj, obj = _clean_entity(m.group("s")), _clean_entity(m.group("o"))
    if len(subj) < 3 or len(obj) < 3 or subj == obj:
        return None
    return {"subject": subj, "relation": rel, "object": obj, "negated": bool(m.group("neg")), "method": "rule_v1"}


def extract_stats(sentence: str) -> list:
    out = []
    for test, rx in STAT_PATTERNS:
        for m in rx.finditer(sentence):
            d = m.groupdict()
            out.append({
                "test": test, "stat": d["stat"], "df1": d["df1"], "df2": d.get("df2"),
                "op": d["op"], "p": d["p"], "raw": m.group(0),
            })
    return out


def language_of(sentence: str) -> str:
    if CAUSAL.search(sentence):
        return "causal"
    if ASSOC.search(sentence):
        return "associational"
    return "descriptive"


def _norm_math(s: str) -> str:
    return s.replace("·", "*").replace("×", "*").replace("−", "-").replace("²", "^2").replace("³", "^3")


def extract_equations(lines) -> list:
    out = []
    for ln in lines:
        raw = _norm_math(ln.text)
        if len(raw) > 90 or raw.count("=") != 1:
            continue
        m = EQ_LINE.match(raw)
        if not m:
            continue
        l, r = m.group("l").strip(), m.group("r").strip()
        if not re.search(r"[A-Za-z]", r):
            continue  # "p = 0.03" style reports are handled as statistics
        if any(len(tok) >= 8 for tok in re.findall(r"[A-Za-z]+", raw)):
            continue  # looks like prose
        out.append({"page": ln.page, "section": ln.section, "text": ln.text, "lhs": l, "rhs": r})
    return out


def extract_claims(parsed) -> list:
    claims = []
    for s in parsed.sentences:
        if s.section in ("references", "front matter"):
            continue
        stats = extract_stats(s.text)
        triple = extract_triple(s.text)
        is_lim = s.section == "limitations" or bool(LIMITATION_CUE.search(s.text))
        if is_lim:
            kind = "limitation"
        elif FINDING_CUE.search(s.text) or triple:
            kind = "finding"
        elif stats:
            kind = "statistical_report"
        else:
            continue
        claims.append({
            "text": s.text, "page": s.page, "section": s.section, "kind": kind,
            "meta": {"language": language_of(s.text), "triple": triple, "stats": stats, "extraction": "rule_v1"},
        })
    for tb in getattr(parsed, "tables", []):
        hdr = [h.lower() for h in tb["rows"][0]]
        claims.append({"text": f"Table ({len(tb['rows']) - 1} rows): " + " | ".join(tb["rows"][0]), "page": tb["page"], "section": "table",
                       "kind": "table", "meta": {"rows": tb["rows"], "header": hdr, "extraction": "pymupdf_find_tables"}})
    for eq in extract_equations(parsed.lines):
        claims.append({
            "text": eq["text"], "page": eq["page"], "section": eq["section"], "kind": "equation_candidate",
            "meta": {"lhs": eq["lhs"], "rhs": eq["rhs"], "extraction": "rule_v1"},
        })
    return claims


def triples_contradict(a: dict, b: dict) -> bool:
    if a["subject"] != b["subject"] or a["object"] != b["object"]:
        return False
    if a["relation"] == b["relation"]:
        return a["negated"] != b["negated"]
    return not a["negated"] and not b["negated"]
