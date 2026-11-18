import math
import re
from typing import Optional


MASS_TO_KG = {
    "kg": 1.0,
    "kgs": 1.0,
    "kilogram": 1.0,
    "kilograms": 1.0,
    "g": 0.001,
    "gram": 0.001,
    "grams": 0.001,
    "mg": 0.000001,
    "milligram": 0.000001,
    "milligrams": 0.000001,
    "lb": 0.45359237,
    "lbs": 0.45359237,
    "pound": 0.45359237,
    "pounds": 0.45359237,
    "oz": 0.028349523125,
    "ounce": 0.028349523125,
    "ounces": 0.028349523125,
    "tonne": 1000.0,
    "tonnes": 1000.0,
    "metric ton": 1000.0,
    "metric tons": 1000.0,
    "ton": 907.18474,
    "tons": 907.18474,
    "short ton": 907.18474,
    "short tons": 907.18474,
    "long ton": 1016.0469088,
    "long tons": 1016.0469088,
}


def normalize_unit(unit: str) -> str:
    normalized = re.sub(r"\s+", " ", unit.strip().lower())
    normalized = normalized.rstrip(".")
    return normalized


def convert_units(value: float, from_unit: str, to_unit: str = "kg") -> float:
    """Convert a numeric mass value between supported mass units."""
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError("value must be a finite number")

    source = normalize_unit(from_unit)
    target = normalize_unit(to_unit)
    if source not in MASS_TO_KG:
        raise ValueError(f"unsupported unit: {from_unit}")
    if target not in MASS_TO_KG:
        raise ValueError(f"unsupported unit: {to_unit}")

    return float(value) * MASS_TO_KG[source] / MASS_TO_KG[target]


def convert_to_kg(value: float, from_unit: str) -> float:
    return convert_units(value, from_unit, "kg")


convert = convert_units


_NUMBER = r"(?:\d+(?:[.,]\d+)*(?:\s*(?:e[+-]?\d+)?)?)"
_UNIT = (
    r"(metric\s+tons?|short\s+tons?|long\s+tons?|tonnes?|tons?|kilograms?|"
    r"milligrams?|grams?|pounds?|ounces?|lbs?|kgs?|g|mg|oz)"
)
_MASS_RE = re.compile(
    rf"(?P<quote>(?P<number>{_NUMBER})\s*(?P<unit>{_UNIT}))",
    re.IGNORECASE,
)


def parse_number(number_text: str) -> float:
    text = number_text.strip().lower().replace(" ", "")
    if "e" in text:
        return float(text)
    if "," in text and "." not in text:
        parts = text.split(",")
        if len(parts[-1]) <= 2:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", "")
    return float(text)


def parse_payload_mass(request_text: str) -> Optional[tuple[float, str, str]]:
    """Find the first explicit mass in a request and return kg, original unit, quote."""
    match = _MASS_RE.search(request_text)
    if not match:
        return None

    number = parse_number(match.group("number"))
    unit = normalize_unit(match.group("unit"))
    value_kg = convert_to_kg(number, unit)

    count = 1.0
    quote = match.group("quote").strip()

    each_match = re.search(r"\beach\b", request_text, re.IGNORECASE)
    if each_match and each_match.start() < match.start():
        before_each = request_text[max(0, each_match.start() - 100):each_match.start()]
        count_matches = list(re.finditer(
            r"(?<![\d.,])(?P<count>\d+(?:[.,]\d+)*)\b",
            before_each,
        ))
        if count_matches:
            count = parse_number(count_matches[-1].group("count"))
    else:
        prefix = request_text[max(0, match.start() - 30):match.start()]
        multiplied_prefix = re.search(
            r"(?P<count>\d+(?:[.,]\d+)*)\s*[x×]\s*$",
            prefix,
            re.IGNORECASE,
        )
        if multiplied_prefix:
            count = parse_number(multiplied_prefix.group("count"))
        else:
            suffix = request_text[match.end():match.end() + 30]
            multiplied_suffix = re.match(
                r"\s*[x×]\s*(?P<count>\d+(?:[.,]\d+)*)\b",
                suffix,
                re.IGNORECASE,
            )
            if multiplied_suffix:
                count = parse_number(multiplied_suffix.group("count"))

    value_kg *= count
    return value_kg, unit, quote
