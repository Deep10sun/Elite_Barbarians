import argparse
import json
from pathlib import Path
from statistics import mean
from uuid import uuid4

from .benchmark_methods import full_agent, llm_only, rule_based
from .llm_parser.parser import build_mission
from .llm_utils.schema import Mission, MissionResult, Sourced


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "fixtures" / "benchmark" / "cases.json"
DEFAULT_OUTPUT = ROOT / "benchmark_results.json"


def prepare_cases():
    spec = (ROOT / "rockets" / "falcon9.txt").read_text(encoding="utf-8")
    base = build_mission("Can the Falcon 9 put a 500 kg payload into LEO?", spec)

    if len(base.rocket.stages) != 2:
        raise ValueError("Expected two Falcon 9 stages. Check the parsed spec.")

    base.request.payload_kg = 500.0
    base.request.payload_source_quote = "500 kg"
    base.request.destination = "LEO"
    base.rocket.published_reference = {}

    heavy = base.model_copy(deep=True)
    heavy.request.payload_kg = 100_000.0
    heavy.request.payload_source_quote = "100,000 kg"

    incomplete = base.model_copy(deep=True)
    incomplete.rocket.stages[1].isp_vac_s = Sourced()

    reference_kg = 22_800.0
    cases = [
        (
            "falcon9_leo_feasible",
            base,
            MissionResult(
                verdict="feasible",
                payload_ceiling_kg=reference_kg,
                shortfall_kg=0.0,
            ),
        ),
        (
            "falcon9_leo_infeasible",
            heavy,
            MissionResult(
                verdict="infeasible",
                payload_ceiling_kg=reference_kg,
                shortfall_kg=100_000.0 - reference_kg,
            ),
        ),
        (
            "falcon9_leo_missing_stage2_isp",
            incomplete,
            MissionResult(
                verdict="missing_data",
                missing_fields=["stage2.isp_vac_s"],
            ),
        ),
    ]
    records = [
        {"id": name, "mission": mission.model_dump(), "expected": expected.model_dump()}
        for name, mission, expected in cases
    ]
    CASES.parent.mkdir(parents=True, exist_ok=True)
    CASES.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(records)} cases to {CASES}")


def numeric_error(actual, expected):
    if actual is None or expected is None:
        return None
    return abs(actual - expected)


def score(prediction, expected):
    return {
        "verdict_correct": prediction.verdict == expected.verdict,
        "payload_error_kg": numeric_error(
            prediction.payload_ceiling_kg, expected.payload_ceiling_kg
        ),
        "shortfall_error_kg": numeric_error(
            prediction.shortfall_kg, expected.shortfall_kg
        ),
        "missing_fields_correct": (
            set(prediction.missing_fields) == set(expected.missing_fields)
            if expected.missing_fields else None
        ),
    }


def format_mean(trials, metric, unit=""):
    values = [
        row["scores"][metric] for row in trials
        if row["scores"][metric] is not None
    ]
    if not values:
        return "— (n=0)"
    return f"{mean(values):.1f}{unit} (n={len(values)})"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--trials", type=int, choices=(1, 3, 4, 5), default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if args.prepare:
        prepare_cases()
        return

    if not CASES.exists():
        parser.error("Run with --prepare first to save the starter cases.")

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    methods = {"full_agent": full_agent, "llm_only": llm_only, "rule_based": rule_based}
    run_id = uuid4().hex
    rows = []

    for case in cases:
        mission = Mission.model_validate(case["mission"])
        expected = MissionResult.model_validate(case["expected"])
        for name, method in methods.items():
            for trial in range(1, args.trials + 1):
                nonce = f"{run_id}-{case['id']}-{name}-{trial}"
                row = {
                    "case": case["id"],
                    "method": name,
                    "trial": trial,
                    "expected": expected.model_dump(),
                }
                try:
                    prediction = method(mission.model_copy(deep=True), nonce)
                    row["prediction"] = prediction.model_dump()
                    row["scores"] = score(prediction, expected)
                except Exception as error:
                    row["error"] = f"{type(error).__name__}: {error}"
                rows.append(row)

    args.output.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")

    print(
        "| Method | Verdict correct | Mean ceiling error | "
        "Mean shortfall error | Missing fields correct | Errors |"
    )
    print("|---|---:|---:|---:|---:|---:|")
    for name in methods:
        attempted = [row for row in rows if row["method"] == name]
        completed = [row for row in attempted if "scores" in row]
        verdicts = sum(row["scores"]["verdict_correct"] for row in completed)
        missing_attempts = sum(bool(row["expected"]["missing_fields"]) for row in attempted)
        missing_correct = sum(
            row["scores"]["missing_fields_correct"] is True for row in completed
        )
        ceiling = format_mean(completed, "payload_error_kg", " kg")
        shortfall = format_mean(completed, "shortfall_error_kg", " kg")
        errors = len(attempted) - len(completed)
        print(
            f"| {name} | {verdicts}/{len(attempted)} | {ceiling} | {shortfall} | "
            f"{missing_correct}/{missing_attempts} | {errors} |"
        )
    print(f"\nSaved {len(rows)} trial records to {args.output}")


if __name__ == "__main__":
    main()