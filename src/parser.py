from llm import call_model, extract_json
from schema import MissionRequest, Mission, RocketSpec
from spec_parser import parse_spec

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
- Do not judge feasibility and do not compute anything except unit conversion.

Respond with ONLY a JSON object, no markdown, no commentary:
{
  "payload_kg": number or null,
  "payload_source_quote": str or null,
  "destination": "LEO"|"ISS"|"GTO"|"TLI"|"Moon"|"Mars"|"unknown",
  "target_altitude_km": number or null,
  "ambiguities": [str]
}"""


def parse_request(request_text: str, nonce=None) -> MissionRequest:
    raw = call_model(request_text, system=REQUEST_PROMPT, nonce=nonce)
    try:
        return MissionRequest.model_validate(extract_json(raw))
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


def build_mission(request_text: str, spec_doc_text: str, vehicle_hint: str = "", nonce=None) -> Mission:
    req = parse_request(request_text, nonce=nonce)
    rocket = parse_spec(spec_doc_text, vehicle_hint=vehicle_hint, nonce=nonce)
    return Mission(
        request=req,
        rocket=rocket,
        missing_fields=find_missing(req, rocket),
        ambiguities=req.ambiguities + rocket.ambiguities,
    )