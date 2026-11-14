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
    r'\b(?i:exposure|conditioning|testing|(?:chamber )?test|exposed|conditioned|tested)\s+(?i:at)\s+'
    rf'(?:(?P<temperature>{TEMPERATURE})(?:\s+(?i:and)\s+(?P<humidity_after>{HUMIDITY}))?'
    rf'|(?P<humidity_first>{HUMIDITY})(?:\s+(?i:and)\s+(?P<temperature_after>{TEMPERATURE}))?)'
    rf'(?:\s+(?i:for)\s+(?P<duration>{DURATION}))?\s*[.!]?\s*$'
)
AMBIGUOUS = re.compile(
    r'\b(?:or|versus|vs|respectively|before|then|subsequently|followed by|'
    r'preconditioning|preconditioned|cycles?|cyclic|if|whether|would|could|might|'
    r'planned|proposed|recommended|not|never|no|nominal(?:ly)?|approximately|about|'
    r'except|unless|alternatively|instead|expected|simulated|hypothetical)\b',
    re.IGNORECASE,
)


def extract_exposure(statement, start_offset):
    """Return exact source spans for explicit condition values. Missing fields stay absent."""
    if AMBIGUOUS.search(statement) or statement.rstrip().endswith('?'):
        return {}
    match = CONDITIONS.search(statement)
    if match is None:
        return {}
    # A second condition outside the terminal clause could belong to a different arm or stage.
    preceding = statement[:match.start()]
    if re.search(rf'(?:{TEMPERATURE}|{HUMIDITY}|{DURATION})\b', preceding):
        return {}

    groups = {
        'temperature': 'temperature' if match['temperature'] else 'temperature_after',
        'relative_humidity': 'humidity_after' if match['humidity_after'] else 'humidity_first',
        'duration': 'duration',
    }
    result = {}
    for field, group in groups.items():
        quote = match[group]
        if quote is None:
            continue
        number = re.match(rf'[+−-]?{NUMBER}', quote).group()
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
        if first is not None and second is not None:
            comparisons.append({
                'field': field,
                'state': 'matches' if first['value'] == second['value'] else 'differs',
                'left': first,
                'right': second,
            })
    return comparisons
