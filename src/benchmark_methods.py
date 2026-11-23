import math

from .ascent_loop.agent import run_agent
from .ascent_loop.physics import build_rocket, simulate_ascent
from .ascent_loop.transfer import calculate_transfer
from .llm_parser.parser import find_missing
from .llm_utils.llm import call_model, extract_json
from .llm_utils.schema import Mission, MissionResult


LEO_BUDGET_MS = 9_300.0
TRANSFER_RESERVE_FRACTION = 0.05


def result_for_payload(verdict, requested_kg, ceiling_kg):
    shortfall = None
    if ceiling_kg is not None:
        shortfall = max(0.0, requested_kg - ceiling_kg)

    return MissionResult(
        verdict=verdict,
        payload_ceiling_kg=ceiling_kg,
        shortfall_kg=shortfall,
    )


def full_agent(mission: Mission, nonce: str) -> MissionResult:
    missing = find_missing(mission.request, mission.rocket)
    if missing:
        return MissionResult(verdict="missing_data", missing_fields=missing)

    output = run_agent(mission, iterations=5, request_nonce=nonce)
    if output["status"] != "ok":
        raise ValueError(f"Agent validation failed: {output.get('validation')}")

    facts = output["facts"]
    return result_for_payload(
        facts["initial_verdict"],
        mission.request.payload_kg,
        facts["ceiling_kg_stock"],
    )


def llm_only(mission: Mission, nonce: str) -> MissionResult:
    result = call_model(
        mission.model_dump_json(exclude={"rocket": {"published_reference"}}),
        system=(
            "Evaluate the original payload request using only the supplied "
            "mission and stock vehicle. Use a fixed LEO budget of 9300 m/s. "
            "Your entire response must be a single valid JSON object. "
            "Start with { and end with }. Omit headings, Markdown, "
            "equations, code fences, and explanations. "
            "Use exactly these keys: verdict, payload_ceiling_kg, missing_fields. "
            "Set verdict to feasible, infeasible, or missing_data. "
            "Set payload_ceiling_kg to a number or null. "
            "Set missing_fields to an array of strings. If required data "
            "is missing, do not guess. Name missing stage fields like "
            "stage2.isp_vac_s, using one-based stage numbers."
        ),
        max_tokens=8000,
        nonce=nonce,
    )
    prediction = MissionResult.model_validate(extract_json(result))

    prediction.shortfall_kg = None
    if (
        prediction.verdict != "missing_data"
        and prediction.payload_ceiling_kg is not None
        and mission.request.payload_kg is not None
    ):
        prediction.shortfall_kg = max(
            0.0, mission.request.payload_kg - prediction.payload_ceiling_kg
        )
    return prediction


def rule_based(mission: Mission, nonce: str) -> MissionResult:
    missing = find_missing(mission.request, mission.rocket)
    if missing:
        return MissionResult(verdict="missing_data", missing_fields=missing)

    rocket_spec = {
        "name": mission.rocket.name,
        "stages": [
            {
                "dry_mass_kg": stage.dry_mass_kg.value,
                "propellant_mass_kg": stage.propellant_mass_kg.value,
                "isp_vac_s": stage.isp_vac_s.value,
                "isp_sl_s": stage.isp_sl_s.value,
                "thrust_sl_n": stage.thrust_sl_n.value,
            }
            for stage in mission.rocket.stages
        ],
    }
    rocket = build_rocket(rocket_spec)
    if any(
        not math.isfinite(value) or value <= 0
        for stage in rocket.stages
        for value in (stage.dry_mass_kg, stage.propellant_mass_kg, stage.isp_vac_s)
    ):
        raise ValueError("Stage masses and specific impulse must be positive.")

    parking_altitude_km = (
        mission.request.target_altitude_km
        if mission.request.target_altitude_km is not None
        else 200.0
    )
    transfer = calculate_transfer(
        mission.request.destination,
        parking_altitude_km,
    )
    if transfer.get("status") != "ok":
        raise ValueError(
            f"Rule-based benchmark has no transfer model for "
            f"{mission.request.destination!r}"
        )
    reserved_transfer_dv = transfer["dv_total_ms"] * (1.0 + TRANSFER_RESERVE_FRACTION)

    def available_delta_v(payload_kg):
        ascent = simulate_ascent(rocket, payload_kg)
        return ascent["dv_total_ms"]

    def required_delta_v():
        return LEO_BUDGET_MS + reserved_transfer_dv

    requested = mission.request.payload_kg
    verdict = (
        "feasible" if available_delta_v(requested) >= required_delta_v()
        else "infeasible"
    )

    ceiling = None
    if available_delta_v(0.0) >= required_delta_v():
        low, high = 0.0, 1_000.0
        while available_delta_v(high) >= required_delta_v():
            high *= 2
        for _ in range(50):
            middle = (low + high) / 2
            if available_delta_v(middle) >= required_delta_v():
                low = middle
            else:
                high = middle
        ceiling = low

    return result_for_payload(verdict, requested, ceiling)