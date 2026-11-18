if __package__.startswith("src."):
    from ..llm_utils.llm import call_model, extract_json
    from ..llm_utils.schema import MissionRequest, Mission, RocketSpec
    from ..llm_utils.units import parse_payload_mass
else:
    from llm_utils.llm import call_model, extract_json
    from llm_utils.schema import MissionRequest, Mission, RocketSpec
    from llm_utils.units import parse_payload_mass
from .spec_parser import parse_spec


class MissingFieldsError(Exception):
    def __init__(self, missing_fields: list[str]):
        self.missing_fields = missing_fields
        super().__init__(
            "Mission cannot continue; missing required fields: "
            + ", ".join(missing_fields)
        )

    def as_response(self) -> dict:
        return {
            "status": "error",
            "error": "missing_fields",
            "missing_fields": self.missing_fields,
        }


REQUEST_PROMPT = """You parse a user's plain-English launch request into JSON.
Rules:
- Copy facts from the request only. If the payload mass is not stated, use null.
  Never guess or use outside knowledge.
- Convert the payload to kg (1 tonne = 1000 kg, 1 lb = 0.45359237 kg) and put the
  exact words you converted from in payload_source_quote.
- destination must be exactly one of: LEO, ISS, GTO, TLI, Moon, Mars, unknown.
  "trans-lunar", "translunar injection" -> TLI. "reach the Moon" / "to the Moon" -> Moon.
  If the destination is vague ("space", "orbit" with no altitude), use "LEO" only if
  the request says low Earth orbit; otherwise use "unknown" and add a note to ambiguities.
- Extract the rocket or vehicle name exactly as stated into vehicle_name. If it is
  not stated, use null and add an ambiguity.
- Do not judge feasibility and do not compute anything except unit conversion.

Respond with ONLY a JSON object, no markdown, no commentary:
{
  "payload_kg": number or null,
  "payload_source_quote": str or null,
  "vehicle_name": str or null,
  "destination": "LEO"|"ISS"|"GTO"|"TLI"|"Moon"|"Mars"|"unknown",
  "target_altitude_km": number or null,
  "ambiguities": [str]
}"""


def parse_request(request_text: str, nonce=None) -> MissionRequest:
    raw = call_model(request_text, system=REQUEST_PROMPT, nonce=nonce)
    try:
        req = MissionRequest.model_validate(extract_json(raw))
        parsed_payload = parse_payload_mass(request_text)
        if parsed_payload is not None:
            payload_kg, _unit, quote = parsed_payload
            req.payload_kg = payload_kg
            req.payload_source_quote = quote
        return req
    except Exception:
        print("Could not parse request output:\n", raw[:2000])
        raise


def find_missing(req: MissionRequest, rocket: RocketSpec) -> list[str]:
    """Deterministic: what do the physics tools need that we don't have?"""
    missing = []
    if req.payload_kg is None:
        missing.append("payload_kg")
    if req.destination == "unknown":
        missing.append("destination")
    if not req.vehicle_name:
        missing.append("vehicle_name")
    if not rocket.stages:
        missing.append("stages")
    for i, st in enumerate(rocket.stages, start=1):
        if st.dry_mass_kg.value is None:
            missing.append(f"stage{i}.dry_mass_kg")
        if st.propellant_mass_kg.value is None:
            missing.append(f"stage{i}.propellant_mass_kg")
        if st.isp_vac_s.value is None:
            missing.append(f"stage{i}.isp_vac_s")
    return missing


def build_mission(request_text: str, spec_doc_text: str, nonce=None) -> Mission:
    req = parse_request(request_text, nonce=nonce)
    rocket = parse_spec(spec_doc_text, vehicle_hint=req.vehicle_name or "", nonce=nonce)
    missing_fields = find_missing(req, rocket)
    if missing_fields:
        raise MissingFieldsError(missing_fields)

    return Mission(
        request=req,
        rocket=rocket,
        ambiguities=req.ambiguities + rocket.ambiguities,
    )