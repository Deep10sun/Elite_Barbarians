import pytest

from src.ascent_loop.physics import Rocket, Stage
from src.ascent_loop.revise import Candidate
from src.ascent_loop.agent import evaluate_candidate
from src.ascent_loop.transfer import calculate_transfer


def test_transfer_uses_requested_parking_altitude():
    default = calculate_transfer("TLI", 200.0)
    high = calculate_transfer("TLI", 1000.0)

    assert default["parking_altitude_km"] == 200.0
    assert high["parking_altitude_km"] == 1000.0
    assert high["dv_total_ms"] != default["dv_total_ms"]


def test_evaluate_candidate_threads_parking_altitude(monkeypatch):
    captured = {}
    rocket = Rocket(
        name="test",
        stages=[Stage(
            dry_mass_kg=1000.0,
            propellant_mass_kg=2000.0,
            isp_vac_s=300.0,
        )],
    )
    candidate = Candidate.start(rocket, 100.0)

    def fake_calculate_transfer(destination, parking_altitude_km=200.0):
        captured["destination"] = destination
        captured["parking_altitude_km"] = parking_altitude_km
        return {
            "destination": destination,
            "parking_altitude_km": parking_altitude_km,
            "status": "ok",
            "dv_total_ms": 0.0,
            "time_s": 0.0,
            "burns": [],
        }

    monkeypatch.setattr(
        "src.ascent_loop.agent.calculate_transfer",
        fake_calculate_transfer,
    )
    evaluate_candidate(candidate, "TLI", 500.0)

    assert captured == {"destination": "TLI", "parking_altitude_km": 500.0}
