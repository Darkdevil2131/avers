"""Extract explicitly stated, single-stage chamber conditions from finding text."""

import re
from decimal import Decimal

FIELDS = {
    'temperature': '°C',
    'relative_humidity': '% RH',
    'duration': 'h',
}
NUMBER = r'\d{1,6}(?:\.\d{1,6})?'
TEMPERATURE = rf'[+−-]?{NUMBER}\s*°\s*C'
HUMIDITY = rf'{NUMBER}\s*%\s*(?i:RH|relative humidity)'
DURATION = rf'{NUMBER}\s*(?i:hours?|hrs?|h|days?|d)'
CONDITIONS = re.compile(
    r'\b(?P<stage>(?i:exposure|conditioning|testing|(?:chamber )?test|exposed|conditioned|tested))\s+(?i:at)\s+'
    rf'(?:(?P<temperature>{TEMPERATURE})(?:\s+(?i:and)\s+(?P<humidity_after>{HUMIDITY}))?'
    rf'|(?P<humidity_first>{HUMIDITY})(?:\s+(?i:and)\s+(?P<temperature_after>{TEMPERATURE}))?)'
    rf'(?:\s+(?i:for)\s+(?P<duration>{DURATION}))?\s*[.!]?\s*$'
)
CONDITIONING_START = r'\b(?i:were(?: then)? )(?P<stage>(?i:conditioned))\s+'
CONDITIONING_END = r'(?:\s+(?i:prior to (?:mechanical )?testing|before testing|before characterization))?\s*[.!]?\s*$'
AT_TEMPERATURE = rf'(?i:at (?:a constant temperature of |laboratory conditions of )?)(?P<temperature>{TEMPERATURE})'
HUMIDITY_VALUE = rf'(?P<humidity_after>{HUMIDITY}|(?i:a relative humidity of ){NUMBER}\s*%)'
FOR_DURATION = rf'(?i:for)\s+(?P<duration>{DURATION})'
CONDITIONING = tuple(re.compile(CONDITIONING_START + values + CONDITIONING_END) for values in (
    rf'{AT_TEMPERATURE}\s+(?i:and)\s+{HUMIDITY_VALUE}(?:\s+{FOR_DURATION})?',
    rf'{FOR_DURATION}\s+{AT_TEMPERATURE}\s+(?i:and)\s+{HUMIDITY_VALUE}',
    rf'(?i:at)\s+{HUMIDITY_VALUE}\s+{FOR_DURATION}\s+{AT_TEMPERATURE}',
))
AMBIGUOUS = re.compile(
    r'\b(?:or|versus|vs|respectively|before|then|subsequently|followed by|'
    r'preconditioning|preconditioned|cycles?|cyclic|if|whether|would|could|might|'
    r'planned|proposed|recommended|not|never|no|nominal(?:ly)?|approximately|about|'
    r'except|unless|alternatively|instead|expected|simulated|hypothetical|assumed|'
    r'failed|should|may|must|at least|at most|minimum|maximum)\b',
    re.IGNORECASE,
)


def extract_exposure(statement, start_offset):
    """Return exact source spans for explicit condition values. Missing fields stay absent."""
    match = CONDITIONS.search(statement)
    if match is None or AMBIGUOUS.search(statement):
        # The dedicated conditioning forms account for the order of the values.
        # Phrases such as "before testing" describe the stage, not a second exposure.
        match = next((match for pattern in CONDITIONING if (match := pattern.search(statement))), None)
        if match is None:
            return {}
    preceding = statement[:match.start()]
    if AMBIGUOUS.search(preceding):
        return {}
    # A second condition outside the terminal clause could belong to a different arm or stage.
    preceding = statement[:match.start()]
    if re.search(rf'(?:{TEMPERATURE}|{HUMIDITY}|{DURATION})\b', preceding):
        return {}

    groups = {
        'temperature': ('temperature', 'temperature_after'),
        'relative_humidity': ('humidity_after', 'humidity_first'),
        'duration': ('duration',),
    }
    captured = match.groupdict()
    stage = {
        'exposed': 'exposure', 'exposure': 'exposure',
        'conditioned': 'conditioning', 'conditioning': 'conditioning',
    }.get(captured['stage'].lower(), 'testing')
    result = {}
    for field, options in groups.items():
        group = next((option for option in options if captured.get(option)), None)
        if group is None:
            continue
        quote = match[group]
        number = re.search(rf'[+−-]?{NUMBER}', quote).group()
        value = Decimal(number.replace('−', '-'))
        if field == 'relative_humidity' and not 0 <= value <= 100:
            continue
        if field == 'temperature' and value < Decimal('-273.15'):
            continue
        if field == 'duration':
            if value <= 0:
                continue
            if quote.rstrip().lower().endswith(('day', 'days', 'd')):
                value *= 24
        result[field] = {
            'value': format(value.normalize() if value else Decimal(0), 'f'),
            'unit': FIELDS[field],
            'stage': stage,
            'quote': quote,
            'start_offset': start_offset + match.start(group),
            'end_offset': start_offset + match.end(group),
        }
    return result


def compare_exposure(left, right):
    """Compare reported values without deciding whether the studies are comparable."""
    left_values = left.get('reported_exposure', {})
    right_values = right.get('reported_exposure', {})
    comparisons = []
    for field in FIELDS:
        first, second = left_values.get(field), right_values.get(field)
        if first is not None and second is not None and first['stage'] == second['stage']:
            comparisons.append({
                'field': field,
                'state': 'matches' if first['value'] == second['value'] else 'differs',
                'left': first,
                'right': second,
            })
    return comparisons
