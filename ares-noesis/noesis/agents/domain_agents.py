from .base import DomainAgent


class MedicineAgent(DomainAgent):
    domain = "medicine"
    connector_names = ["pubmed", "europepmc", "clinicaltrials", "semanticscholar", "openalex", "crossref"]
    allowed_engines = ["statistical_engine", "causal_engine", "logic_engine"]


class TechnologyAgent(DomainAgent):
    domain = "technology"
    connector_names = ["arxiv", "semanticscholar", "openalex", "crossref", "core", "doaj"]
    design_rules = {"benchmark": r"\bbenchmark|state-of-the-art|we evaluate on", "theoretical": r"\btheorem|we prove|lemma",
                    "review": r"\bsurvey\b"}
    allowed_engines = ["math_engine", "statistical_engine", "logic_engine"]
    operations = {"literature_search", "find_implementations"}

    def op_find_implementations(self, msg, res):
        """Public code/dataset repositories related to the topic (GitHub). Provenance + license reported; never treated as evidence."""
        gh = self.connectors_all.get("github") if hasattr(self, "connectors_all") else None
        repos = []
        if gh is None:
            res.status = "unavailable"
            res.errors.append({"connector": "github", "error": "not configured"})
        else:
            from ..connectors.base import ConnectorError, ConnectorUnavailable
            for q in msg.inputs.get("queries", [])[:2]:
                try:
                    repos += [r.model_dump() for r in gh.search(q, int(msg.inputs.get("limit", 5)))]
                except (ConnectorUnavailable, ConnectorError) as e:
                    res.errors.append({"connector": "github", "error": str(e)})
                    res.status = "partial"
        res.outputs["implementations"] = repos


class SpaceAgent(DomainAgent):
    domain = "space"
    connector_names = ["nasa_ads", "arxiv", "openalex", "semanticscholar"]
    design_rules = {"simulation": r"\bsimulat|numerical model", "observational": r"\bobservation|telescope|spectra|survey of",
                    "theoretical": r"\banalytic|theoretical"}
    allowed_engines = ["math_engine", "statistical_engine"]


def _generic(name, connectors, engines):
    """Domain agents for fields beyond the original three. They share the general scholarly connectors; domain-specific connectors
    (e.g. a chemistry or earth-science database) are NOT built, so literature search is the only operation."""
    return type(f"{name.title().replace('_', '')}Agent", (DomainAgent,), {"domain": name, "connector_names": connectors, "allowed_engines": engines})


_GEN = ["openalex", "crossref", "semanticscholar", "core", "arxiv", "europepmc"]
AGENT_CLASSES = {"medicine": MedicineAgent, "technology": TechnologyAgent, "space": SpaceAgent,
                 "chemistry": _generic("chemistry", _GEN, ["math_engine", "statistical_engine", "logic_engine"]),
                 "physics": _generic("physics", _GEN, ["math_engine", "statistical_engine", "logic_engine"]),
                 "earth_science": _generic("earth_science", _GEN, ["statistical_engine", "temporal_engine", "causal_engine"]),
                 "life_science": _generic("life_science", _GEN, ["statistical_engine", "causal_engine", "logic_engine"]),
                 "social_science": _generic("social_science", _GEN, ["statistical_engine", "causal_engine", "temporal_engine"]),
                 "mathematics": _generic("mathematics", _GEN, ["math_engine", "logic_engine"]),
                 "general": _generic("general", _GEN, ["statistical_engine", "logic_engine"])}


def build_agents(connectors: dict) -> dict:
    return {k: v(connectors) for k, v in AGENT_CLASSES.items()}
