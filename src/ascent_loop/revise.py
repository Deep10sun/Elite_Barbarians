"""revise.py - the Revise step: bounded design levers the agent may pull.

The LLM chooses WHAT to change and explains why. This module decides whether
the change is allowed and applies it. Physics constants live here, in code,
so the agent cannot tune its way to a pass.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
import math

if __package__ and __package__.startswith("src."):
    from .physics import Rocket
else:
    from ascent_loop.physics import Rocket

MAX_PROP_INCREASE = 0.15   # max added propellant per stage, fraction of original
STRUCT_PENALTY = 0.025     # kg of extra dry mass per kg of added propellant (tank mass only; assumption)


@dataclass(frozen=True)
class Candidate:
    base: Rocket                 # original, unmodified vehicle
    requested_payload_kg: float  # what the user asked for
    payload_kg: float            # what we are currently testing
    added_prop_kg: tuple         # cumulative added propellant, per stage

    @classmethod
    def start(cls, rocket: Rocket, payload_kg: float) -> "Candidate":
        return cls(rocket, payload_kg, payload_kg, (0.0,) * len(rocket.stages))

    def build(self) -> Rocket:
        stages = []
        for s, add in zip(self.base.stages, self.added_prop_kg):
            stages.append(replace(
                s,
                propellant_mass_kg=s.propellant_mass_kg + add,
                dry_mass_kg=s.dry_mass_kg + STRUCT_PENALTY * add,
            ))
        return Rocket(name=self.base.name, stages=stages)

    def key(self) -> tuple:
        return (round(self.payload_kg), tuple(round(a) for a in self.added_prop_kg))


def apply_revision(cand: Candidate, change: dict, history: set) -> dict:
    """Validate and apply one change. Returns the new candidate or a rejection.

    Allowed changes:
      {"payload_kg": 4000}
      {"add_propellant_kg": 5000, "stage": 2}
    `history` is the set of candidate keys already evaluated.
    """
    allowed = {"payload_kg", "add_propellant_kg", "stage"}
    unknown = set(change) - allowed
    if unknown:
        return {"status": "rejected", "reason": f"unknown fields: {sorted(unknown)}"}

    new = cand
    if "payload_kg" in change:
        try:
            p = float(change["payload_kg"])
        except (TypeError, ValueError):
            return {"status": "rejected", "reason": "payload_kg must be a number"}
        if not math.isfinite(p):
            return {"status": "rejected", "reason": "payload_kg must be finite"}
        if not 0 <= p <= cand.requested_payload_kg:
            return {"status": "rejected",
                    "reason": f"payload must be between 0 and the requested "
                              f"{cand.requested_payload_kg:g} kg"}
        new = replace(new, payload_kg=p)

    if "add_propellant_kg" in change:
        stage = change.get("stage")
        try:
            kg = float(change["add_propellant_kg"])
        except (TypeError, ValueError):
            return {"status": "rejected",
                    "reason": "add_propellant_kg must be a number"}
        n = len(cand.base.stages)
        if isinstance(stage, bool) or not isinstance(stage, int) or not 1 <= stage <= n:
            return {"status": "rejected", "reason": f"stage must be 1..{n}"}
        if not math.isfinite(kg) or kg <= 0:
            return {"status": "rejected", "reason": "add_propellant_kg must be positive"}
        cap = MAX_PROP_INCREASE * cand.base.stages[stage - 1].propellant_mass_kg
        total = cand.added_prop_kg[stage - 1] + kg
        if total > cap:
            return {"status": "rejected",
                    "reason": f"stage {stage} propellant increase capped at "
                              f"{cap:,.0f} kg ({MAX_PROP_INCREASE:.0%}); "
                              f"requested cumulative {total:,.0f} kg"}
        added = list(cand.added_prop_kg)
        added[stage - 1] = total
        new = replace(new, added_prop_kg=tuple(added))

    if new.key() == cand.key():
        return {"status": "rejected", "reason": "change does not alter the candidate"}
    if new.key() in history:
        return {"status": "rejected", "reason": "this candidate was already evaluated"}
    return {"status": "ok", "candidate": new,
            "applied": {"payload_kg": new.payload_kg,
                        "added_prop_kg": list(new.added_prop_kg),
                        "struct_penalty_kg_per_kg": STRUCT_PENALTY}}


if __name__ == "__main__":
    from physics import build_rocket, simulate_ascent
    f9 = {"name": "Falcon 9", "stages": [
        {"dry_mass_kg": 22200, "propellant_mass_kg": 411000,
         "isp_vac_s": 311, "isp_sl_s": 282, "thrust_sl_n": 7607e3},
        {"dry_mass_kg": 4000, "propellant_mass_kg": 107500, "isp_vac_s": 348}]}
    need = 3131.345 * 1.05        # TLI dv + 5% reserve
    cand = Candidate.start(build_rocket(f9), 8000)
    history = {cand.key()}

    def margin(c):
        return simulate_ascent(c.build(), c.payload_kg)["margin_ms"] - need

    print("start      margin:", round(margin(cand), 1))
    for change in ({"add_propellant_kg": 5000, "stage": 2},
                   {"add_propellant_kg": 50000, "stage": 2},  # over the cap
                   {"add_propellant_kg": 11000, "stage": 2},  # up to the cap
                   {"payload_kg": 6000},
                   {"payload_kg": 6000}):                     # true repeat
        r = apply_revision(cand, change, history)
        if r["status"] == "ok":
            cand = r["candidate"]; history.add(cand.key())
            print("applied", change, "-> margin:", round(margin(cand), 1))
        else:
            print("rejected", change, "->", r["reason"])