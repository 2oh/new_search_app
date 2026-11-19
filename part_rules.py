"""Eligibility shared by the workbook and composite modes."""
import pandas as pd

DEFAULT_RULES = ({'match_type': 'startswith', 'value': '16'},)


def clean(value):
    if value is None or pd.isna(value):
        return ''
    text = str(value).strip()
    return '' if text.lower() in ('nan', 'none') else text


def is_zero_quantity(value):
    text = clean(value)
    if not text:
        return False
    try:
        return float(text.replace(',', '')) == 0.0
    except ValueError:
        return False


def eligible(number, raw_pg, resolved_pg, quantity, color, rules=DEFAULT_RULES):
    number, raw_pg, resolved_pg = map(clean, (number, raw_pg, resolved_pg))
    if is_zero_quantity(quantity) or clean(color) or not (number or resolved_pg):
        return False
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        value = clean(rule.get('value'))
        if value and str(rule.get('match_type', '')).strip().lower() == 'startswith':
            if number.startswith(value) or resolved_pg.startswith(value):
                return False
    return True
