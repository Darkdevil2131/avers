"""Experiment planner: templates + real power analysis. A plan is a PROPOSAL - never an executed experiment."""
from ..engines.stats_engine import sample_size_two_sample_t

DOMAIN_DESIGN = {
    "medicine": {"design": "preclinical in-vitro/in-vivo controlled experiment (clinical testing only after expert review)",
                 "ethics": ["IRB/IACUC approval before any human or animal work", "no clinical claims from this proposal"],
                 "controls": ["vehicle/placebo control", "randomization", "blinded outcome assessment"]},
    "technology": {"design": "controlled benchmark / ablation study with repeated seeds",
                   "ethics": ["license compliance for datasets/code"],
                   "controls": ["fixed dataset splits", "same hardware/software versions", "baseline implementations from the literature"]},
    "space": {"design": "validated numerical simulation followed by ground test / observational dataset comparison",
              "ethics": ["export-control and mission-safety review where applicable"],
              "controls": ["documented initial conditions", "model-version pinning", "comparison against published measurements"]},
}
DEFAULT = {"design": "controlled laboratory/computational experiment", "ethics": ["domain-expert review"],
           "controls": ["matched control condition", "randomized run order"]}


def plan(h: dict, assumed_d: float = 0.5, alpha: float = 0.05, power: float = 0.8) -> dict:
    dom = (h.get("domain") or [""])[0]
    tpl = DOMAIN_DESIGN.get(dom, DEFAULT)
    ind, dep = h["variables"]["independent"], h["variables"]["dependent"]
    n = sample_size_two_sample_t(assumed_d, alpha, power)
    pred = h["plausibility_assessment"].get("predicted_sign")
    exp = ("an increase" if pred and pred > 0 else "a decrease" if pred else "a difference")
    return {
        "executed": False, "status": "proposal_only",
        "objective": h["statement"], "hypothesis_id": h["hypothesis_id"], "design": tpl["design"],
        "variables": {"independent": ind, "dependent": dep, "mediators": h["variables"]["mediators"], "controls": tpl["controls"]},
        "required_data": h["required_data"],
        "sample_size": {"n_per_group": n, "assumed_effect_size_d": assumed_d, "alpha": alpha, "power": power,
                        "method": "two-sample t-test, noncentral t (scipy)",
                        "caveat": "effect size is an ASSUMPTION (Cohen 'medium'); replace with a pilot-derived estimate"},
        "evaluation_metrics": [f"change in {dep} between {ind} levels", "effect size with 95% CI", "pre-registered primary outcome"],
        "expected_observations": f"If the hypothesis holds: {exp} in {dep} as {ind} varies" + (f", with {h['variables']['mediators'][0]} changing in the same direction" if h["variables"]["mediators"] else ""),
        "success_criteria": f"CI for the effect on {dep} excludes zero in the predicted direction at alpha={alpha}",
        "failure_criteria": f"CI for the effect includes zero (with adequate power) or is in the opposite direction => hypothesis refuted/unsupported",
        "risks": ["confounding from uncontrolled conditions", "under-powered if true effect < assumed"],
        "ethical_requirements": tpl["ethics"],
        "reproducibility_requirements": ["pre-register analysis", "record software/model/instrument versions", "publish raw data and code"],
    }
