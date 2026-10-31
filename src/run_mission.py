import sys
from parser import build_mission

request = sys.argv[1] if len(sys.argv) > 1 else \
    "Can this rocket put a 5,000 kg payload on a trans-lunar trajectory?"
spec_path = sys.argv[2] if len(sys.argv) > 2 else "rockets/falcon.txt"

mission = build_mission(request, open(spec_path).read(), vehicle_hint="Falcon")
print(mission.model_dump_json(indent=2))