import math
import statistics

CAPABILITIES = {
    "describe_sample": {
        "version": "1", "input": "2–10000 finite numeric observations",
        "output": "count, mean, sample standard deviation, minimum, maximum",
        "assumptions": ["Input observations are numeric and use consistent units"],
        "limitations": ["Descriptive statistics only; no causal or population inference"],
    },
    "convert_unit": {
        "version": "1", "input": "finite value, source unit, target unit",
        "output": "converted value and units",
        "assumptions": ["Units are selected from the supported registry"],
        "limitations": ["Length, time and mass only"],
    },
}
UNITS = {
    "m": ("length", 1), "cm": ("length", .01), "mm": ("length", .001),
    "km": ("length", 1000), "s": ("time", 1), "min": ("time", 60),
    "h": ("time", 3600), "kg": ("mass", 1), "g": ("mass", .001),
}


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e100:
        raise ValueError("Values must be finite numbers within ±1e100")
    return value


def execute(name, parameters):
    if name == "describe_sample":
        values = parameters.get("values")
        if not isinstance(values, list) or not 2 <= len(values) <= 10000:
            raise ValueError("Supply 2–10000 observations")
        values = [finite(value) for value in values]
        return {"n": len(values), "mean": statistics.mean(values),
                "sample_stdev": statistics.stdev(values), "min": min(values), "max": max(values)}
    if name == "convert_unit":
        value = finite(parameters.get("value"))
        source, target = parameters.get("from"), parameters.get("to")
        if source not in UNITS or target not in UNITS or UNITS[source][0] != UNITS[target][0]:
            raise ValueError("Select supported units of the same dimension")
        return {"value": value * UNITS[source][1] / UNITS[target][1], "unit": target}
    raise ValueError("Unknown capability")
