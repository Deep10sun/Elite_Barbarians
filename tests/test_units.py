import pytest

from src.ascent_loop.physics import validate_rocket
from src.llm_utils.units import (
    convert_to_kg,
    convert_units,
    parse_payload_mass,
)


@pytest.mark.parametrize("field", ["dry_mass_kg", "propellant_mass_kg"])
@pytest.mark.parametrize("value", [0, -1, float("inf"), float("-inf"), float("nan")])
def test_validate_rocket_rejects_nonpositive_or_nonfinite_stage_masses(field, value):
    stage = {
        "dry_mass_kg": 100.0,
        "propellant_mass_kg": 200.0,
        "isp_vac_s": 300.0,
    }
    stage[field] = value

    result = validate_rocket({"name": "test", "stages": [stage]})

    assert result["status"] == "invalid"


def test_convert_pounds_to_kilograms():
    assert convert_to_kg(10, "lb") == pytest.approx(4.5359237)


def test_convert_metric_tonnes_to_pounds():
    assert convert_units(1, "metric ton", "lb") == pytest.approx(2204.6226218487757)


def test_parse_comma_separated_payload():
    assert parse_payload_mass("Can it carry a 5,000 kg payload?") == (
        5000.0,
        "kg",
        "5,000 kg",
    )


def test_parse_pound_payload():
    parsed = parse_payload_mass("Launch 11 pounds to orbit")
    assert parsed is not None
    assert parsed[0] == pytest.approx(4.98951607)
    assert parsed[1] == "pounds"
    assert parsed[2] == "11 pounds"


def test_parse_repeated_human_payload():
    parsed = parse_payload_mass(
        "Can the Falcon 9 put 3 human males (each weighing 100Kgs) "
        "in trans lunar orbit"
    )
    assert parsed is not None
    assert parsed[0] == pytest.approx(300.0)
    assert parsed[1] == "kgs"
    assert parsed[2] == "100Kgs"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Launch 3 x 100 kg", 300.0),
        ("Launch 100 kg x 3", 300.0),
    ],
)
def test_parse_multiplication_payload(text, expected):
    parsed = parse_payload_mass(text)
    assert parsed is not None
    assert parsed[0] == pytest.approx(expected)
