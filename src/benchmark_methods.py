import math

from .ascent_loop.agent import run_agent
from .llm_parser.parser import find_missing
from .llm_utils.llm import call_model, extract_json
from .llm_utils.schema import Mission, MissionResult


LEO_BUDGET_MS = 9_300.0


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
    if mission.request.destination != "LEO":
        raise ValueError("The starter rule-based benchmark supports LEO only.")

    stages = [
        (s.dry_mass_kg.value, s.propellant_mass_kg.value, s.isp_vac_s.value)
        for s in mission.rocket.stages
    ]
    if any(not math.isfinite(x) or x <= 0 for stage in stages for x in stage):
        raise ValueError("Stage masses and specific impulse must be positive.")

    def available_delta_v(payload_kg):
        carried_mass = payload_kg
        total = 0.0
        for dry_mass, propellant_mass, isp in reversed(stages):
            burnout_mass = carried_mass + dry_mass
            total += 9.80665 * isp * math.log1p(propellant_mass / burnout_mass)
            carried_mass = burnout_mass + propellant_mass
        return total

    requested = mission.request.payload_kg
    verdict = (
        "feasible" if available_delta_v(requested) >= LEO_BUDGET_MS
        else "infeasible"
    )

    ceiling = None
    if available_delta_v(0.0) >= LEO_BUDGET_MS:
        low, high = 0.0, 1_000.0
        while available_delta_v(high) >= LEO_BUDGET_MS:
            high *= 2
        for _ in range(50):
            middle = (low + high) / 2
            if available_delta_v(middle) >= LEO_BUDGET_MS:
                low = middle
            else:
                high = middle
        ceiling = low

    return result_for_payload(verdict, requested, ceiling)