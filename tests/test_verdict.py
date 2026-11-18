import json
from pathlib import Path

import pytest

from src.ascent_loop.agent import derive_verdict, _deterministic_explanation


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("verdict_feasible.json", ("feasible", "feasible")),
        ("verdict_infeasible_as_requested.json", ("infeasible_as_requested", "infeasible")),
        ("verdict_infeasible.json", ("infeasible", "infeasible")),
    ],
)
def test_saved_result_verdict_logic(name, expected):
    result = json.loads((FIXTURES / name).read_text())
    verdict, as_requested = derive_verdict(
        result["request"]["payload_kg"], result["history"]
    )
    assert (verdict, as_requested) == expected
    assert result["facts"]["verdict"] == verdict
    assert _deterministic_explanation(result["facts"])
