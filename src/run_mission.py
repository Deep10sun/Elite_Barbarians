from pathlib import Path
import json
import sys

if __package__:
    from .ascent_loop.agent import run_agent
    from .llm_parser.parser import MissingFieldsError, build_mission
else:
    from ascent_loop.agent import run_agent
    from llm_parser.parser import MissingFieldsError, build_mission


DEFAULT_REQUEST = (
    "Can the Falcon rocket put a 5,000 kg payload on a trans-lunar trajectory?"
)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    request = args[0] if args else DEFAULT_REQUEST
    spec_path = Path(args[1]) if len(args) > 1 else (
        Path(__file__).resolve().parents[1] / "rockets" / "falcon9.txt"
    )
    iterations = int(args[2]) if len(args) > 2 else 5

    try:
        mission = build_mission(request, spec_path.read_text(encoding="utf-8"))
    except MissingFieldsError as error:
        print(json.dumps(error.as_response(), indent=2))
        return 1

    output = json.loads(mission.model_dump_json())
    output["agent"] = run_agent(mission, iterations=iterations)
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
