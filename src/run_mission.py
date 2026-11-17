from pathlib import Path
import json
import sys

if __package__:
    from .llm_parser.parser import MissingFieldsError, build_mission
    from .ascent_loop.physics import (
        build_rocket,
        find_max_payload,
        simulate_ascent,
        validate_rocket,
    )
    from .ascent_loop.transfer import calculate_transfer
else:
    from llm_parser.parser import MissingFieldsError, build_mission
    from ascent_loop.physics import (
        build_rocket,
        find_max_payload,
        simulate_ascent,
        validate_rocket,
    )
    from ascent_loop.transfer import calculate_transfer


def run_ascent(mission) -> dict:
    """Run deterministic ascent physics using the parsed mission values."""
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

    validation = validate_rocket(rocket_spec)
    if validation["status"] != "ok":
        return {"status": "error", "validation": validation}

    rocket = build_rocket(rocket_spec)
    ascent = simulate_ascent(
        rocket,
        payload_kg=mission.request.payload_kg,
    )
    ascent["max_payload"] = find_max_payload(rocket)
    return {"status": "ok", **ascent}

request = sys.argv[1] if len(sys.argv) > 1 else \
    "Can the Falcon rocket put a 5,000 kg payload on a trans-lunar trajectory?"
spec_path = sys.argv[2] if len(sys.argv) > 2 else "rockets/falcon9.txt"
if len(sys.argv) <= 2:
    spec_path = Path(__file__).resolve().parents[1] / spec_path

try:
    mission = build_mission(
        request,
        Path(spec_path).read_text(encoding="utf-8"),
    )
except MissingFieldsError as error:
    print(json.dumps(error.as_response(), indent=2))
    raise SystemExit(1)

output = json.loads(mission.model_dump_json())
output["ascent"] = run_ascent(mission)
output["transfer"] = calculate_transfer(mission.request.destination)
print(json.dumps(output, indent=2))