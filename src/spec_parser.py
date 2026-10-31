from llm import call_model, extract_json
from schema import RocketSpec

PROMPT = """You extract rocket specifications from document text into JSON.
Rules:
- Copy values from the text only. If a value is not stated, use null.
  Never use outside knowledge to fill a gap.
- Convert to kg, seconds, newtons. For every value record the original unit
  and the exact quote from the document it came from.
- Keep sea-level and vacuum Isp/thrust separate. If the text says "Isp" without
  saying which, leave both null and add a note to ambiguities.
- If the document describes several variants, extract only the one named in
  the user message, or put the conflict in ambiguities.
- Payload capacities go in published_reference, never in stage fields.
- Do not do any calculations other than unit conversion.

Respond with ONLY a JSON object, no markdown fences, no commentary, matching
this shape. Every "Sourced" field is an object with value, unit_as_written,
source_quote (each may be null).

{
  "name": str,
  "variant": str or null,
  "stages": [
    {
      "dry_mass_kg": Sourced,
      "propellant_mass_kg": Sourced,
      "isp_vac_s": Sourced,
      "isp_sl_s": Sourced,
      "thrust_vac_n": Sourced,
      "thrust_sl_n": Sourced
    }
  ],
  "published_reference": {"leo_payload_kg": number},
  "ambiguities": [str]
}"""

def parse_spec(doc_text: str, vehicle_hint: str = "", nonce=None) -> RocketSpec:
  prompt = f"Vehicle: {vehicle_hint}\n\nDocument:\n{doc_text}"
  raw = call_model(prompt, system=PROMPT, nonce=nonce)
  try:
    return RocketSpec.model_validate(extract_json(raw))
  except Exception:
    print("Could not parse this model output:\n", raw[:2000])
    raise