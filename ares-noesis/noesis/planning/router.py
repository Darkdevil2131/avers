"""Router: lexicon scoring -> single / cross_domain / unknown / out_of_scope. (Heuristic; replaceable by a classifier.)"""
import re

LEXICON = {
    "medicine": ["patient", "clinical", "trial", "disease", "drug", "therap", "treatment", "cancer", "protein", "gene", "cell line", "stem cell",
                 "mice", "dose", "diagnos", "biomarker", "mortality", "vaccin", "pathway", "receptor", "symptom", "pharmac",
                 "biomedical", "tumou?r", "infection", "enzyme", "neuro"],
    "technology": ["algorithm", "neural", "network", "benchmark", "software", "hardware", "latency", "throughput", "compiler",
                   "machine learning", "deep learning", "transformer", "gpu", "encryption", "battery", "semiconductor",
                   "photovoltaic", "perovskite", "graphene", "material", "electrolyte", "circuit", "sensor", "robot", "coating"],
    "space": ["orbit", "spacecraft", "satellite", "planet", "exoplanet", "galax", "stellar", "telescope", "cosmic", "lunar",
              "mars", "rocket", "astrophys", "solar wind", "gravitation", "vacuum", "re-?entry", "propulsion"],
    "chemistry": ["reaction", "catalyst", "catalys", "synthesis", "molecul", "polymer", "solvent", "spectroscop", "compound", "ligand", "oxidation", "yield of"],
    "physics": ["quantum", "photon", "particle", "superconduct", "magnetic", "thermodynamic", "relativity", "laser", "plasma", "condensed matter", "lattice"],
    "earth_science": ["climate", "ocean", "atmospher", "glacier", "seismic", "carbon emission", "greenhouse", "ecosystem", "geolog", "hydrolog", "rainfall"],
    "life_science": ["species", "genome", "evolution", "photosynthes", "ecolog", "biodiversity", "microb", "taxonom", "metabolism"],
    "social_science": ["economic", "inflation", "policy", "survey respondents", "education", "labor market", "behavio", "demograph", "wage"],
    "mathematics": ["theorem", "conjecture", "lemma", "prime number", "topolog", "combinatori", "differential equation", "algebra"],
}
SCIENCE_MARKERS = re.compile(r"\b(hypothes\w+|experiment\w*|study|analysis|data|model|method|results?|paper|research)\b", re.I)


def route(text: str) -> dict:
    t = text.lower()
    scores = {d: len({k for k in kws if re.search(r"\b" + k, t)}) for d, kws in LEXICON.items()}
    top = max(scores.values())
    if top == 0:
        mode = "unknown" if len(SCIENCE_MARKERS.findall(text)) >= 2 else "out_of_scope"
        return {"mode": mode, "domains": [], "scores": scores,
                "rationale": "no domain vocabulary matched" + ("; scientific wording present" if mode == "unknown" else "")}
    domains = [d for d, s in sorted(scores.items(), key=lambda x: -x[1]) if s >= max(1, 0.4 * top)]
    return {"mode": "cross_domain" if len(domains) > 1 else "single", "domains": domains, "scores": scores,
            "rationale": f"vocabulary hits per domain: {scores}"}
