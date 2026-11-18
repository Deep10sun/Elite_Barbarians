"""LLM coordinator for the deterministic mission-feasibility tools.

The model may select a revision or a reporting action, but it never performs
physics or mutates a vehicle directly.  Candidate changes are accepted only
by :func:`apply_revision`.
"""
from __future__ import annotations

import json
from typing import Any

if __package__ and __package__.startswith("src."):
    from ..llm_utils.llm import call_model, extract_json
else:
    from llm_utils.llm import call_model, extract_json

from .physics import (
    build_rocket,
    find_max_payload,
    simulate_ascent,
    validate_rocket,
)
from .revise import Candidate, apply_revision
from .transfer import calculate_transfer, check_margin


AGENT_PROMPT = """You coordinate a rocket mission using deterministic tool output.
You may decide what to try, but you must not calculate delta-v, margins, payload
ceilings, or any other number. Every number in a response must be copied from
the tool results or be part of a proposed change.

Return ONLY JSON with this shape:
{
  "action": "revise" | "find_max_payload" | "finish",
  "change": object or null,
  "explanation": "brief rationale grounded in the history"
}

Allowed changes (one per turn):
  {"add_propellant_kg": number, "stage": integer}
  {"payload_kg": number}

Strategy, in this order:
1. Experiment with propellant first. While any stage has remaining cap in
   revision_limits, propose adding that stage's full remaining cap, copying the
   value from revision_limits. Try one stage per turn, and try every stage that
   still has headroom.
2. After each accepted change, compare margin_ms with the previous evaluation in
   the history. Accepted changes stay in effect and cannot be undone. If adding
   propellant to a stage lowered the margin, do not add more to that stage.
3. When no stage has remaining cap, or propellant changes no longer improve the
   margin, and the mission is still infeasible, call "find_max_payload".
4. Once payload_ceiling is present, revise payload_kg to that ceiling. Reducing
   payload is the last resort. Do not reduce payload while a useful propellant
   experiment remains.
5. Use "finish" only when the mission is feasible, or when no allowed change
   remains.

The propellant_needed_kg value is only an optimistic estimate. Do not propose a
change that exceeds revision_limits, and do not alter a rejected proposal.
payload_ceiling applies to the current vehicle: if you change propellant after
it was computed, it is stale and must be requested again.w
"""


def _rocket_spec(mission: Any) -> dict:
    return {
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


def evaluate_candidate(
    candidate: Candidate,
    destination: str,
    parking_altitude_km: float = 200.0,
) -> dict:
    """Run all deterministic mission checks for one candidate."""
    rocket = candidate.build()
    ascent = simulate_ascent(rocket, candidate.payload_kg)
    transfer = calculate_transfer(destination, parking_altitude_km)
    transfer["feasible"] = bool(
        ascent.get("reached_orbit") and transfer.get("status") == "ok"
    )
    stage2 = rocket.stages[-1]
    margin = check_margin(
        ascent,
        transfer,
        payload_kg=candidate.payload_kg,
        stage2_dry_mass_kg=stage2.dry_mass_kg,
        stage2_propellant_mass_kg=stage2.propellant_mass_kg,
        stage2_isp_s=stage2.isp_vac_s,
    )
    return {"ascent": ascent, "transfer": transfer, "margin": margin}


def _candidate_view(candidate: Candidate) -> dict:
    return {
        "payload_kg": candidate.payload_kg,
        "added_propellant_kg": list(candidate.added_prop_kg),
    }


def _revision_limits(candidate: Candidate) -> dict:
    return {
        "max_additional_propellant_kg": [
            round(0.15 * stage.propellant_mass_kg - added, 1)
            for stage, added in zip(
                candidate.base.stages, candidate.added_prop_kg
            )
        ],
        "propellant_cap_fraction": 0.15,
    }


def derive_verdict(requested_kg: float, history: list[dict]) -> tuple[str, str]:
    """Derive verdict outcomes solely from saved candidate evaluations."""
    closed = [
        event for event in history
        if event.get("event") in {"evaluation", "evaluation_cached"}
        and event.get("candidate")
        and event.get("margin", {}).get("feasible")
    ]
    as_requested_closed = any(
        abs(float(event["candidate"]["payload_kg"]) - requested_kg) < 1e-6
        for event in closed
    )
    revised_closed = any(
        float(event["candidate"]["payload_kg"]) < requested_kg - 1e-6
        for event in closed
    )
    if as_requested_closed:
        return "feasible", "feasible"
    if revised_closed:
        return "infeasible_as_requested", "infeasible"
    return "infeasible", "infeasible"


def _deterministic_explanation(facts: dict) -> str:
    requested = facts["requested_kg"]
    ceiling = facts["ceiling_kg"]
    verdict = facts["verdict"]
    if verdict == "feasible":
        changes = facts.get("recommended_changes")
        additions = changes.get("added_propellant_kg") if changes else None
        text = f"Feasible as requested: {requested:g} kg closes"
        populated_additions = [value for value in (additions or []) if value]
        if populated_additions:
            text += " with " + " and ".join(
                f"+{value:g} kg stage {i} propellant"
                for i, value in enumerate(additions or [], 1)
                if value
            )
        return text + "."
    if verdict == "infeasible_as_requested":
        text = (
            f"Not feasible as requested: {requested:g} kg exceeds the ceiling "
            f"of {ceiling:g} kg"
        )
        if facts["shortfall_kg"] is not None:
            text += f" by {facts['shortfall_kg']:g} kg"
        if facts["shortfall_pct"] is not None:
            text += f" ({facts['shortfall_pct']:.1f}%)"
        text += "."
        changes = facts["recommended_changes"] or {}
        payload = changes.get("payload_kg")
        additions = changes.get("added_propellant_kg")
        if payload is not None:
            text += f" Feasible at {payload:g} kg"
            if additions:
                text += " with " + " and ".join(
                    f"+{value:g} kg stage {i} propellant"
                    for i, value in enumerate(additions, 1)
                    if value
                )
            text += "."
        return text
    ceiling_text = f"The ceiling is {ceiling:g} kg." if ceiling is not None else "No payload ceiling was found."
    return f"Infeasible: {ceiling_text} Nothing closes, even at near-zero payload."


def _decision(raw: str) -> dict:
    try:
        value = extract_json(raw)
    except ValueError as error:
        raise RuntimeError(f"agent returned invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError("agent response must be a JSON object")
    action = value.get("action")
    if action not in {"revise", "find_max_payload", "finish"}:
        raise RuntimeError(f"agent returned unsupported action: {action!r}")
    if "explanation" not in value or not isinstance(value["explanation"], str):
        raise RuntimeError("agent response must include an explanation string")
    return value


def run_agent(mission: Any, iterations: int = 5) -> dict:
    """Coordinate up to ``iterations`` model decisions for a parsed mission."""
    if iterations < 1:
        raise ValueError("iterations must be at least 1")
    if mission.request.payload_kg is None:
        raise ValueError("mission payload_kg is required before running the agent")

    rocket = _rocket_spec(mission)
    validation = validate_rocket(rocket)
    if validation["status"] != "ok":
        return {"status": "error", "validation": validation, "history": []}

    candidate = Candidate.start(build_rocket(rocket), mission.request.payload_kg)
    evaluated = {candidate.key()}
    evaluations: dict[tuple, dict] = {}
    history: list[dict] = []
    rationale = ""
    max_payload = None
    turn = 0
    decisions_made = 0
    rejections_in_a_row = 0
    termination_reason = "iteration_limit"
    initial_candidate = _candidate_view(candidate)
    initial_result = None
    parking_altitude_km = (
        mission.request.target_altitude_km
        if mission.request.target_altitude_km is not None
        else 200.0
    )

    while decisions_made < iterations and rejections_in_a_row < 3:
        iteration = decisions_made
        key = candidate.key()
        result = evaluations.get(key)
        if result is None:
            result = evaluate_candidate(
                candidate,
                mission.request.destination,
                parking_altitude_km,
            )
            evaluations[key] = result
            if initial_result is None:
                initial_result = result
            history.append({
                "turn": turn,
                "iteration": iteration,
                "event": "evaluation",
                "candidate": _candidate_view(candidate),
                **result,
            })
            turn += 1
        else:
            history.append({
                "turn": turn,
                "iteration": iteration,
                "event": "evaluation_cached",
                "candidate": _candidate_view(candidate),
            })
            turn += 1

        if result["margin"].get("feasible"):
            if abs(candidate.payload_kg - mission.request.payload_kg) < 1e-6:
                termination_reason = "feasible_as_requested"
            else:
                termination_reason = "feasible_after_revision"
            break

        prompt = json.dumps(
            {"mission": {"destination": mission.request.destination,
                         "requested_payload_kg": candidate.requested_payload_kg},
             "current_candidate": _candidate_view(candidate),
             "revision_limits": _revision_limits(candidate),
             "payload_ceiling": max_payload,
             "history": history},
            indent=2,
        )
        response = _decision(call_model(
            prompt, system=AGENT_PROMPT, nonce=f"agent-turn-{turn}"
        ))
        history.append({
            "turn": turn,
            "iteration": iteration,
            "event": "decision",
            "action": response["action"],
            "explanation": response["explanation"],
        })
        turn += 1
        action = response["action"]

        if action == "finish":
            decisions_made += 1
            termination_reason = "infeasible_no_solution"
            break
        if action == "find_max_payload":
            max_payload = find_max_payload(
                candidate.build(),
                required_extra_dv_ms=result["margin"]["reserved_transfer_dv_ms"],
            )
            history.append({
                "turn": turn,
                "iteration": iteration,
                "event": "find_max_payload",
                "candidate": _candidate_view(candidate),
                "result": max_payload,
            })
            turn += 1
            decisions_made += 1
            rejections_in_a_row = 0
            continue
        change = response.get("change")
        if not isinstance(change, dict):
            history.append({
                "turn": turn,
                "iteration": iteration,
                "event": "revision",
                "revision": {
                    "status": "rejected", "reason": "change must be an object",
                },
            })
            turn += 1
            rejections_in_a_row += 1
            continue
        revision = apply_revision(candidate, change, evaluated)
        history_revision = {
            key: value for key, value in revision.items() if key != "candidate"
        }
        history.append({
            "turn": turn,
            "iteration": iteration,
            "event": "revision",
            "change": change,
            "revision": history_revision,
        })
        turn += 1
        if revision["status"] == "ok":
            candidate = revision["candidate"]
            evaluated.add(candidate.key())
            decisions_made += 1
            rejections_in_a_row = 0
            max_payload = None
        else:
            rejections_in_a_row += 1

    final = evaluations.get(candidate.key())
    if final is None:
        final = evaluate_candidate(
            candidate,
            mission.request.destination,
            parking_altitude_km,
        )
        evaluations[candidate.key()] = final
        history.append({
            "turn": turn,
            "iteration": decisions_made,
            "event": "evaluation",
            "candidate": _candidate_view(candidate),
            **final,
        })
        turn += 1
    current_candidate = _candidate_view(candidate)
    if max_payload is None:
        max_payload = find_max_payload(
            candidate.build(),
            required_extra_dv_ms=final["margin"]["reserved_transfer_dv_ms"],
        )
        history.append({
            "turn": turn,
            "iteration": decisions_made,
            "event": "find_max_payload",
            "candidate": _candidate_view(candidate),
            "result": max_payload,
        })
        turn += 1
    requested_payload = mission.request.payload_kg
    if initial_result is None:
        initial_result = final

    first_evaluation = next(
        (event for event in history if event.get("event") == "evaluation"),
        None,
    )
    as_requested_evaluation = first_evaluation
    closed_candidates = [
        event for event in history
        if event.get("event") in {"evaluation", "evaluation_cached"}
        and event.get("margin", {}).get("feasible")
    ]
    # Cached entries do not carry the margin; include only evaluated closing events.
    closed_candidates = [
        event for event in closed_candidates
        if event.get("candidate") is not None
    ]
    as_requested_closed = any(
        abs(float(event["candidate"]["payload_kg"]) - requested_payload) < 1e-6
        for event in closed_candidates
    )
    revised_closed = any(
        float(event["candidate"]["payload_kg"]) < requested_payload - 1e-6
        or any(float(value) > 0 for value in event["candidate"].get("added_propellant_kg", []))
        for event in closed_candidates
    )

    verdict, verdict_as_requested = derive_verdict(requested_payload, history)

    ceiling = max_payload.get("max_payload_kg") if max_payload else None
    if ceiling is None:
        for event in reversed(history):
            if event.get("event") == "find_max_payload" and isinstance(event.get("result"), dict):
                ceiling = event["result"].get("max_payload_kg")
                if ceiling is not None:
                    break

    required_extra_dv = final["margin"].get("reserved_transfer_dv_ms", 0.0)
    stock_max = find_max_payload(
        candidate.base,
        required_extra_dv_ms=required_extra_dv,
    )
    ceiling_stock = stock_max.get("max_payload_kg")
    history.append({
        "turn": turn,
        "iteration": decisions_made,
        "event": "find_max_payload_stock",
        "candidate": {"payload_kg": 0.0, "added_propellant_kg": [0.0] * len(candidate.base.stages)},
        "result": stock_max,
    })
    turn += 1

    shortfall = None if ceiling is None else max(0.0, requested_payload - ceiling)
    shortfall_pct = (
        None if not requested_payload or shortfall is None
        else round(100.0 * shortfall / requested_payload, 1)
    )

    closing_event = next(
        (
            event for event in reversed(closed_candidates)
        ),
        None,
    )
    recommended = None
    if closing_event is not None:
        closing_candidate = closing_event["candidate"]
        recommended = {
            "payload_kg": closing_candidate["payload_kg"],
            "added_propellant_kg": closing_candidate.get("added_propellant_kg", []),
        }
    elif ceiling is not None:
        recommended = {
            "payload_kg": ceiling,
            "added_propellant_kg": list(candidate.added_prop_kg),
        }

    facts = {
        "verdict": verdict,
        "verdict_as_requested": verdict_as_requested,
        "initial_verdict": (
            "feasible" if initial_result["margin"].get("feasible") else "infeasible"
        ),
        "final_verdict": (
            "feasible" if final["margin"].get("feasible") else "infeasible"
        ),
        "requested_kg": requested_payload,
        "ceiling_kg": ceiling,
        "ceiling_kg_stock": ceiling_stock,
        "shortfall_kg": shortfall,
        "shortfall_pct": shortfall_pct,
        "recommended_changes": recommended,
        "final_margin_ms": final["margin"].get("margin_ms"),
        "initial_margin_ms": initial_result["margin"].get("margin_ms"),
    }
    explanation = _deterministic_explanation(facts)

    if verdict == "feasible":
        termination_reason = "feasible_as_requested"
    elif verdict == "infeasible_as_requested":
        termination_reason = "feasible_after_revision"
    elif rejections_in_a_row >= 3:
        termination_reason = "iteration_limit"
    elif decisions_made >= iterations:
        termination_reason = "iteration_limit"
    else:
        termination_reason = "infeasible_no_solution"
    report = {
        "status": "ok",
        "verdict": facts["verdict"],
        "requested_payload_kg": requested_payload,
        "as_requested_evaluation": as_requested_evaluation,
        "initial_candidate": initial_candidate,
        "candidate": current_candidate,
        **final,
        "history": history,
        "facts": facts,
        "explanation": explanation,
        "termination_reason": termination_reason,
        "iterations_requested": iterations,
        "iterations_used": decisions_made,
    }
    if max_payload is not None:
        report["max_payload"] = max_payload
    return report
