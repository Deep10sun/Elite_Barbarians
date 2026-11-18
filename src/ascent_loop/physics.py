"""physics.py - deterministic tools for the mission feasibility agent.

Ascent model v1: staged rocket equation minus an explicit loss budget.
Every assumption is returned in the output so the report can state it.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import math

G0 = 9.80665          # m/s^2
V_LEO = 7800.0        # m/s, approx circular orbital speed at ~200 km
G_EARTH = 9.80665


@dataclass
class Stage:
    dry_mass_kg: float
    propellant_mass_kg: float
    isp_vac_s: float
    isp_sl_s: Optional[float] = None       # only meaningful for stage 1
    thrust_sl_n: Optional[float] = None    # used for the liftoff T/W check


@dataclass
class Rocket:
    name: str
    stages: list[Stage]


REQUIRED = ("dry_mass_kg", "propellant_mass_kg", "isp_vac_s")


def validate_rocket(spec: dict) -> dict:
    """Gate between parser and simulator. Never guesses; halts on gaps.

    `spec` is the parser output flattened to plain numbers:
    {"name": ..., "stages": [{"dry_mass_kg": 22200, ...}, ...]}
    """
    missing, bad = [], []
    if not spec.get("stages"):
        return {"status": "needs_input", "missing": ["stages"]}
    for i, st in enumerate(spec.get("stages", []), start=1):
        for f in REQUIRED:
            if st.get(f) is None:
                missing.append(f"stage{i}.{f}")
        dry_mass = st.get("dry_mass_kg")
        propellant_mass = st.get("propellant_mass_kg")
        for field_name, mass in (
            ("dry_mass_kg", dry_mass),
            ("propellant_mass_kg", propellant_mass),
        ):
            if mass is not None:
                try:
                    valid_mass = math.isfinite(mass) and mass > 0
                except (TypeError, ValueError):
                    valid_mass = False
                if not valid_mass:
                    bad.append(f"stage{i}: {field_name}={mass} must be finite and positive")
        if (isinstance(dry_mass, (int, float))
                and isinstance(propellant_mass, (int, float))
                and math.isfinite(dry_mass)
                and math.isfinite(propellant_mass)
                and propellant_mass <= dry_mass):
                bad.append(f"stage{i}: propellant mass not above dry mass")
        isp = st.get("isp_vac_s")
        if isp is not None and not (200 <= isp <= 460):
            bad.append(f"stage{i}: isp_vac_s={isp} outside 200-460 s")
    if missing:
        return {"status": "needs_input", "missing": missing}
    if bad:
        return {"status": "invalid", "problems": bad}
    return {"status": "ok"}


def build_rocket(spec: dict) -> Rocket:
    stages = [Stage(**{k: v for k, v in s.items()
                       if k in Stage.__dataclass_fields__}) for s in spec["stages"]]
    return Rocket(name=spec.get("name", "unnamed"), stages=stages)


def stage_dv(isp_s: float, m0: float, mf: float) -> float:
    return isp_s * G0 * math.log(m0 / mf)


def liftoff_twr(rocket: Rocket, payload_kg: float) -> Optional[float]:
    """Thrust-to-weight at liftoff. Must be > 1 or the rocket never leaves the pad."""
    s1 = rocket.stages[0]
    if s1.thrust_sl_n is None:
        return None
    m_total = payload_kg + sum(s.dry_mass_kg + s.propellant_mass_kg
                               for s in rocket.stages)
    return s1.thrust_sl_n / (m_total * G_EARTH)


def simulate_ascent(rocket: Rocket, payload_kg: float,
                    losses_ms: float = 1500.0,
                    v_target_ms: float = V_LEO,
                    s1_isp_mode: str = "average") -> dict:
    """Delta-v budget for ascent to a parking orbit.

    s1_isp_mode: "vac" uses vacuum Isp for stage 1 (optimistic),
                 "average" uses the mean of sea-level and vacuum Isp.
    """
    stages = rocket.stages
    # mass above each stage = payload + everything in later stages (wet)
    burn_table, dv_total = [], 0.0
    for i, s in enumerate(stages):
        above = payload_kg + sum(t.dry_mass_kg + t.propellant_mass_kg
                                 for t in stages[i + 1:])
        m0 = above + s.dry_mass_kg + s.propellant_mass_kg
        mf = above + s.dry_mass_kg
        if i == 0 and s1_isp_mode == "average" and s.isp_sl_s:
            isp = 0.5 * (s.isp_sl_s + s.isp_vac_s)
        else:
            isp = s.isp_vac_s
        dv = stage_dv(isp, m0, mf)
        dv_total += dv
        burn_table.append({"stage": i + 1, "m0_kg": round(m0), "mf_kg": round(mf),
                           "isp_used_s": isp, "dv_ms": round(dv, 1)})

    dv_needed = v_target_ms + losses_ms
    twr = liftoff_twr(rocket, payload_kg)
    lifts_off = False if twr is None else twr > 1.0
    return {
        "payload_kg": payload_kg,
        "reached_orbit": bool(lifts_off and dv_total >= dv_needed),
        "dv_total_ms": round(dv_total, 1),
        "dv_needed_ms": round(dv_needed, 1),
        "margin_ms": round(dv_total - dv_needed, 1),
        "liftoff_twr": None if twr is None else round(twr, 2),
        "burn_table": burn_table,
        "assumptions": {"losses_ms": losses_ms, "v_target_ms": v_target_ms,
                        "s1_isp_mode": s1_isp_mode,
                        "model": "rocket equation minus fixed loss budget"},
    }


def find_max_payload(rocket: Rocket, hi_kg: float = 100_000.0,
                     tol_kg: float = 1.0,
                     required_extra_dv_ms: float = 0.0, **kw) -> dict:
    """Bisection on payload: largest payload meeting the supplied delta-v budget."""
    if required_extra_dv_ms < 0:
        raise ValueError("required_extra_dv_ms cannot be negative")

    def qualifies(payload_kg: float) -> bool:
        result = simulate_ascent(rocket, payload_kg, **kw)
        return bool(
            result["reached_orbit"]
            and result["margin_ms"] >= required_extra_dv_ms
        )

    if not qualifies(0.0):
        return {"max_payload_kg": 0.0, "note": "cannot reach orbit even empty"}
    lo = 0.0
    while hi_kg - lo > tol_kg:
        mid = 0.5 * (lo + hi_kg)
        if qualifies(mid):
            lo = mid
        else:
            hi_kg = mid
    return {"max_payload_kg": round(lo)}


if __name__ == "__main__":
    f9 = {"name": "Falcon 9 (Block 5, expendable)", "stages": [
        {"dry_mass_kg": 22200, "propellant_mass_kg": 411000,
         "isp_vac_s": 311, "isp_sl_s": 282, "thrust_sl_n": 7607e3},
        {"dry_mass_kg": 4000, "propellant_mass_kg": 107500, "isp_vac_s": 348},
    ]}
    print(validate_rocket(f9))
    r = build_rocket(f9)
    for mode in ("vac", "average"):
        res = simulate_ascent(r, 22800, s1_isp_mode=mode)
        print(f"\n[{mode}] 22,800 kg ->", res["reached_orbit"],
              "margin", res["margin_ms"], "m/s, TWR", res["liftoff_twr"])
        print("   max payload:", find_max_payload(r, s1_isp_mode=mode))