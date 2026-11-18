"""Deterministic transfer calculations and two-body orbit propagation.

The model is intentionally low fidelity: impulsive burns, circular parking
orbits, coplanar Hohmann transfers, and patched conics. Results are estimates
for mission screening, not flight-dynamics guidance.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

MU_EARTH = 3.986004418e14
MU_SUN = 1.32712440018e20
R_EARTH = 6_378_137.0
AU = 149_597_870_700.0
MOON_DISTANCE = 384_400_000.0
MARS_DISTANCE = 1.523679 * AU
TRANSFER_RESERVE_FRACTION = 0.05


@dataclass(frozen=True)
class OrbitState:
    """Two-dimensional inertial state in the orbit's perifocal plane."""

    time_s: float
    position_m: tuple[float, float]
    velocity_m_s: tuple[float, float]


def _validate_radius(radius_m: float, name: str) -> None:
    if radius_m <= 0:
        raise ValueError(f"{name} must be positive")


def circular_speed(radius_m: float, mu: float = MU_EARTH) -> float:
    """Return circular-orbit speed at ``radius_m``."""
    _validate_radius(radius_m, "radius_m")
    return math.sqrt(mu / radius_m)


def vis_viva_speed(radius_m: float, semi_major_axis_m: float,
                   mu: float = MU_EARTH) -> float:
    """Return speed at a radius on an elliptical orbit."""
    _validate_radius(radius_m, "radius_m")
    _validate_radius(semi_major_axis_m, "semi_major_axis_m")
    value = mu * (2.0 / radius_m - 1.0 / semi_major_axis_m)
    if value <= 0:
        raise ValueError("orbit parameters produce no real velocity")
    return math.sqrt(value)


def hohmann_transfer(r1_m: float, r2_m: float,
                     mu: float = MU_EARTH) -> dict:
    """Calculate the two impulsive burns and time of a coplanar Hohmann transfer."""
    _validate_radius(r1_m, "r1_m")
    _validate_radius(r2_m, "r2_m")
    if r1_m == r2_m:
        return {
            "r1_m": r1_m, "r2_m": r2_m, "dv1_ms": 0.0, "dv2_ms": 0.0,
            "dv_total_ms": 0.0, "time_s": 0.0,
        }

    a_transfer = 0.5 * (r1_m + r2_m)
    v1 = circular_speed(r1_m, mu)
    v2 = circular_speed(r2_m, mu)
    v_periapsis = vis_viva_speed(r1_m, a_transfer, mu)
    v_apoapsis = vis_viva_speed(r2_m, a_transfer, mu)
    dv1 = abs(v_periapsis - v1)
    dv2 = abs(v2 - v_apoapsis)
    return {
        "r1_m": r1_m,
        "r2_m": r2_m,
        "transfer_semi_major_axis_m": a_transfer,
        "dv1_ms": round(dv1, 3),
        "dv2_ms": round(dv2, 3),
        "dv_total_ms": round(dv1 + dv2, 3),
        "time_s": round(math.pi * math.sqrt(a_transfer ** 3 / mu), 3),
    }


def propagate_orbit(semi_major_axis_m: float, eccentricity: float,
                    times_s: Iterable[float],
                    mu: float = MU_EARTH,
                    initial_true_anomaly_rad: float = 0.0) -> list[OrbitState]:
    """Propagate an elliptic two-body orbit and return position/velocity states.

    The orbit starts at ``initial_true_anomaly_rad``. Coordinates are in the
    perifocal plane, with periapsis on the positive x-axis.
    """
    times_s = list(times_s)
    _validate_radius(semi_major_axis_m, "semi_major_axis_m")
    if not 0 <= eccentricity < 1:
        raise ValueError("eccentricity must be in [0, 1)")
    if any(time < 0 for time in times_s):
        raise ValueError("times_s cannot contain negative values")

    p = semi_major_axis_m * (1.0 - eccentricity ** 2)
    n = math.sqrt(mu / semi_major_axis_m ** 3)
    initial_e = 2.0 * math.atan2(
        math.sqrt(1.0 - eccentricity) * math.sin(initial_true_anomaly_rad / 2.0),
        math.sqrt(1.0 + eccentricity) * math.cos(initial_true_anomaly_rad / 2.0),
    )
    initial_mean = initial_e - eccentricity * math.sin(initial_e)
    states = []

    for time_s in times_s:
        mean_anomaly = initial_mean + n * time_s
        eccentric_anomaly = math.pi if eccentricity > 0.8 else mean_anomaly
        converged = False
        for _ in range(50):
            correction = (
                eccentric_anomaly
                - eccentricity * math.sin(eccentric_anomaly)
                - mean_anomaly
            ) / (1.0 - eccentricity * math.cos(eccentric_anomaly))
            eccentric_anomaly -= correction
            if abs(correction) < 1e-12:
                converged = True
                break
        if not converged:
            raise RuntimeError(
                f"eccentric anomaly solver did not converge at t={time_s}"
            )

        true_anomaly = 2.0 * math.atan2(
            math.sqrt(1.0 + eccentricity) * math.sin(eccentric_anomaly / 2.0),
            math.sqrt(1.0 - eccentricity) * math.cos(eccentric_anomaly / 2.0),
        )
        radius = p / (1.0 + eccentricity * math.cos(true_anomaly))
        radial_speed = math.sqrt(mu / p) * eccentricity * math.sin(true_anomaly)
        transverse_speed = math.sqrt(mu / p) * (
            1.0 + eccentricity * math.cos(true_anomaly)
        )
        cos_nu, sin_nu = math.cos(true_anomaly), math.sin(true_anomaly)
        states.append(OrbitState(
            time_s=float(time_s),
            position_m=(radius * cos_nu, radius * sin_nu),
            velocity_m_s=(
                radial_speed * cos_nu - transverse_speed * sin_nu,
                radial_speed * sin_nu + transverse_speed * cos_nu,
            ),
        ))
    return states


def calculate_transfer(destination: str, parking_altitude_km: float = 200.0) -> dict:
    """Return a destination transfer budget and its propagation model."""
    if parking_altitude_km < 0:
        raise ValueError("altitudes cannot be negative")
    destination = destination.strip()
    parking_radius = R_EARTH + parking_altitude_km * 1000.0

    if destination in {"LEO", "ISS"}:
        assumptions = "payload is already in the circular parking orbit"
        if destination == "ISS":
            assumptions += (
                "; ISS altitude and 51.6-degree inclination/plane change are "
                "not modeled"
            )
        return {
            "destination": destination,
            "parking_altitude_km": parking_altitude_km,
            "status": "ok",
            "dv_total_ms": 0.0,
            "time_s": 0.0,
            "burns": [],
            "assumptions": assumptions,
        }

    if destination == "GTO":
        geo_radius = 42_164_000.0
        transfer = hohmann_transfer(parking_radius, geo_radius)
        return {
            "destination": destination,
            "parking_altitude_km": parking_altitude_km,
            "status": "ok",
            "dv_total_ms": transfer["dv1_ms"],
            "time_s": transfer["time_s"],
            "burns": [{"name": "GTO injection", "dv_ms": transfer["dv1_ms"]}],
            "assumptions": (
                "coplanar Hohmann transfer from circular LEO to the GTO "
                "apogee radius; circularization at GEO is not modeled"
            ),
        }

    if destination in {"TLI", "Moon"}:
        lunar_transfer = hohmann_transfer(
            parking_radius, MOON_DISTANCE, MU_EARTH
        )
        result = {
            "destination": destination,
            "parking_altitude_km": parking_altitude_km,
            "status": "ok",
            "dv_total_ms": lunar_transfer["dv1_ms"],
            "time_s": lunar_transfer["time_s"],
            "burns": [
                {"name": "trans-lunar injection", "dv_ms": lunar_transfer["dv1_ms"]}
            ],
            "arrival_speed_ms": vis_viva_speed(
                MOON_DISTANCE,
                lunar_transfer["transfer_semi_major_axis_m"],
                MU_EARTH,
            ),
            "assumptions": (
                "Hohmann-to-lunar-distance estimate using Earth gravity only; "
                "TLI excludes lunar orbit insertion"
            ),
        }
        if destination == "Moon":
            result["assumptions"] += "; lunar capture is not modeled"
        return result

    if destination == "Mars":
        earth_departure = hohmann_transfer(AU, MARS_DISTANCE, MU_SUN)
        mars_arrival_excess = earth_departure["dv2_ms"]
        earth_orbit_speed = circular_speed(AU, MU_SUN)
        departure_excess = abs(
            vis_viva_speed(AU, earth_departure["transfer_semi_major_axis_m"], MU_SUN)
            - earth_orbit_speed
        )
        earth_escape = math.sqrt(
            departure_excess ** 2 + 2.0 * MU_EARTH / parking_radius
        ) - circular_speed(parking_radius)
        return {
            "destination": destination,
            "parking_altitude_km": parking_altitude_km,
            "status": "ok",
            "dv_total_ms": round(earth_escape, 3),
            "time_s": earth_departure["time_s"],
            "burns": [
                {"name": "Earth departure", "dv_ms": round(earth_escape, 3)}
            ],
            "mars_arrival_excess_ms": mars_arrival_excess,
            "assumptions": (
                "heliocentric Earth-to-Mars Hohmann estimate; burns include "
                "Earth departure only; Mars capture is not modeled"
            ),
        }

    return {
        "destination": destination,
        "status": "unsupported",
        "message": f"no transfer model for destination {destination!r}",
    }


def check_margin(ascent: dict, transfer: dict, payload_kg: float,
                 stage2_dry_mass_kg: float, stage2_propellant_mass_kg: float,
                 stage2_isp_s: float,
                 reserve_fraction: float = TRANSFER_RESERVE_FRACTION) -> dict:
    """Compare ascent margin with the reserved transfer delta-v requirement."""
    if reserve_fraction < 0:
        raise ValueError("reserve_fraction cannot be negative")
    transfer_dv = transfer.get("dv_total_ms")
    ascent_margin = ascent.get("margin_ms")
    if transfer_dv is None or ascent_margin is None:
        return {
            "status": "error",
            "message": "ascent and transfer results must include delta-v values",
        }

    reserved_transfer_dv = transfer_dv * (1.0 + reserve_fraction)
    margin_ms = ascent_margin - reserved_transfer_dv
    required_dv = reserved_transfer_dv
    margin_pct = None if required_dv == 0 else margin_ms / required_dv * 100.0
    propellant_needed = 0.0
    if margin_ms < 0:
        if stage2_isp_s <= 0:
            return {
                "status": "error",
                "message": "stage2_isp_s must be positive for propellant conversion",
            }
        shortfall_ms = -margin_ms
        mass_before = payload_kg + stage2_dry_mass_kg + stage2_propellant_mass_kg
        exhaust_velocity = stage2_isp_s * 9.80665
        propellant_needed = mass_before * (
            1.0 - math.exp(-shortfall_ms / exhaust_velocity)
        )

    return {
        "status": "ok",
        "feasible": bool(
            ascent.get("reached_orbit")
            and transfer.get("feasible", transfer.get("status") == "ok")
            and margin_ms >= 0
        ),
        "margin_ms": round(margin_ms, 1),
        "margin_pct": None if margin_pct is None else round(margin_pct, 2),
        "reserve_fraction": reserve_fraction,
        "transfer_dv_ms": round(transfer_dv, 1),
        "reserved_transfer_dv_ms": round(reserved_transfer_dv, 1),
        "propellant_needed_kg": round(propellant_needed, 1),
        "assumptions": (
            "transfer reserve is a fixed fraction; propellant equivalent uses "
            "the inverse rocket equation and stage 2 Isp"
        ),
    }