from pathlib import Path
import json
import sys

if __package__:
    from .llm_parser.parser import MissingFieldsError, build_mission
else:
    from llm_parser.parser import MissingFieldsError, build_mission

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

print(mission.model_dump_json(indent=2))