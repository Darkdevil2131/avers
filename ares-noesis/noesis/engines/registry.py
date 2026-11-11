"""Capability profiles for engines; the planner matches required operations to engines."""
from . import causal_engine, logic_engine, math_engine, simulation_engine, stats_engine, temporal_engine, validation_engine

ENGINES = {
    "statistical_engine": {
        "capabilities": ["check_reports", "grim", "grim_table", "sample_size", "meta_analysis", "simulate_power"],
        "input_types": ["statistical_claims", "tabular_data"], "resource_class": "light",
        "output_schema": "statistical_result_v1", "run": stats_engine.run},
    "math_engine": {
        "capabilities": ["check_equations", "equivalent", "evaluate", "check_dimensions"],
        "input_types": ["equations"], "resource_class": "light",
        "output_schema": "math_result_v1", "run": math_engine.run},
    "simulation_engine": {
        "capabilities": ["ode", "two_body"],
        "input_types": ["governing_equations", "initial_conditions"], "resource_class": "medium",
        "output_schema": "simulation_result_v1", "run": simulation_engine.run},
    "logic_engine": {
        "capabilities": ["check_consistency"],
        "input_types": ["propositions"], "resource_class": "light",
        "output_schema": "logic_result_v1", "run": logic_engine.run},
    "causal_engine": {
        "capabilities": ["audit", "backdoor", "estimate_effect"],
        "input_types": ["claims", "causal_graph"], "resource_class": "light",
        "output_schema": "causal_result_v1", "run": causal_engine.run},
    "temporal_engine": {
        "capabilities": ["stance_trend"],
        "input_types": ["dated_stance_points"], "resource_class": "light",
        "output_schema": "temporal_result_v1", "run": temporal_engine.run},
    "validation_engine": {
        "capabilities": ["validate_beliefs"],
        "input_types": ["beliefs"], "resource_class": "light",
        "output_schema": "validation_result_v1", "run": validation_engine.run},
}


def engine_for(operation: str):
    for name, prof in ENGINES.items():
        if operation in prof["capabilities"]:
            return name
    return None


def profiles() -> dict:
    return {k: {kk: vv for kk, vv in v.items() if kk != "run"} for k, v in ENGINES.items()}
