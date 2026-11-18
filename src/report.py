"""Generate a deterministic mission report from a saved agent result."""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?(?:\d+(?:,\d{3})*|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _numbers(text: str) -> list[float]:
    return [float(token.replace(",", "")) for token in NUMBER_RE.findall(text)]


def validate_llm_numbers(text: str, facts: dict[str, Any]) -> bool:
    """Return whether every numeric token in *text* is supported by *facts*."""
    allowed = []
    for value in facts.values():
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            number = float(value)
            allowed.extend((number, _significant(number, 2), _significant(number, 3)))
    for number in _numbers(text):
        if not any(
            abs(number - candidate) <= max(1e-6, abs(candidate) * 1e-6)
            for candidate in allowed
        ):
            return False
    return True


def _unsupported_numbers(text: str, facts: dict[str, Any]) -> list[float]:
    allowed = []
    for value in facts.values():
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            allowed.extend((float(value), _significant(float(value), 2), _significant(float(value), 3)))
    return [
        number for number in _numbers(text)
        if not any(abs(number - candidate) <= max(1e-6, abs(candidate) * 1e-6) for candidate in allowed)
    ]


def _significant(value: float, digits: int) -> float:
    if value == 0:
        return 0.0
    return round(value, digits - int(math.floor(math.log10(abs(value)))) - 1)


def _fmt(value: Any, unit: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, (int, float)):
        return f"{value:,.1f}{unit}" if isinstance(value, float) else f"{value:,}{unit}"
    return f"{value}{unit}"


def _agent(result: dict[str, Any]) -> dict[str, Any]:
    return result.get("agent", result)


def _verdict(agent: dict[str, Any]) -> str:
    facts = agent.get("facts", {})
    verdict = facts.get("verdict") or agent.get("verdict")
    if verdict == "feasible":
        return "FEASIBLE"
    if verdict == "infeasible_as_requested":
        return "NOT FEASIBLE AS REQUESTED"
    if facts.get("ceiling_kg") is not None and facts.get("ceiling_kg") < facts.get("requested_kg", 0):
        return "FEASIBLE WITH CHANGES"
    return "NOT FEASIBLE"


def _facts(result: dict[str, Any]) -> dict[str, Any]:
    agent = _agent(result)
    ascent, transfer, margin = agent.get("ascent", {}), agent.get("transfer", {}), agent.get("margin", {})
    saved_facts = agent.get("facts", {})
    requested = saved_facts.get("requested_kg", result.get("request", {}).get("payload_kg", agent.get("candidate", {}).get("payload_kg")))
    ceiling = saved_facts.get("ceiling_kg", agent.get("max_payload", {}).get("max_payload_kg"))
    values = {
        "requested_payload_kg": requested,
        "max_payload_kg": ceiling,
        "ceiling_kg_stock": saved_facts.get("ceiling_kg_stock"),
        "shortfall_kg": saved_facts.get("shortfall_kg"),
        "shortfall_pct": saved_facts.get("shortfall_pct"),
        "recommended_changes": saved_facts.get("recommended_changes"),
        "verdict": saved_facts.get("verdict"),
        "propellant_margin_kg": None if margin.get("propellant_needed_kg") is None else -margin.get("propellant_needed_kg", 0),
        "propellant_margin_pct": None,
        "required_delta_v_ms": ascent.get("dv_needed_ms", 0) + transfer.get("reserved_transfer_dv_ms", margin.get("reserved_transfer_dv_ms", 0)),
        "available_delta_v_ms": ascent.get("dv_total_ms"),
        "margin_ms": margin.get("margin_ms"),
        "transfer_delta_v_ms": transfer.get("dv_total_ms"),
    }
    total_prop = sum(
        stage.get("propellant_mass_kg", {}).get("value", 0) or 0
        for stage in result.get("rocket", {}).get("stages", [])
    )
    if total_prop:
        values["propellant_margin_pct"] = values["propellant_margin_kg"] / total_prop * 100
    return {key: value for key, value in values.items() if value is not None}


def _prose(result: dict[str, Any], facts: dict[str, Any], kind: str, use_llm: bool) -> tuple[str, bool]:
    agent = _agent(result)
    verdict = _verdict(agent)
    requested = facts.get("requested_payload_kg")
    ceiling = facts.get("max_payload_kg")
    if kind == "verdict":
        template = agent.get("explanation") or f"{verdict}: the request is for {_fmt(requested, ' kg')} on {result.get('request', {}).get('destination', agent.get('transfer', {}).get('destination', 'the stated destination'))} using {result.get('rocket', {}).get('name', 'the selected rocket')}."
        system = "Write one concise verdict sentence. Use only numbers in the supplied facts. Do not calculate, round, or add any number."
    else:
        if ceiling is not None and ceiling < (requested or 0):
            template = f"Reduce the payload to about {_fmt(ceiling, ' kg')} or increase available propellant; the requested {_fmt(requested, ' kg')} exceeds the transfer-aware ceiling."
        elif verdict == "FEASIBLE":
            template = "The proposed mission closes the modeled ascent and transfer budgets; retain the stated vehicle and payload, subject to the listed assumptions."
        else:
            template = "The mission does not close the modeled budgets. Reduce the payload or add propellant, then rerun the deterministic checks."
        system = "Write one concise plain-English recommendation. Use only numbers in the supplied facts. Do not calculate, round, or add any number."
    if not use_llm:
        return template, True
    try:
        from .llm_utils.llm import call_model
        prompt = json.dumps({
            "facts": facts,
            "verdict": verdict,
            "destination": result.get("request", {}).get("destination", agent.get("transfer", {}).get("destination")),
            "rocket": result.get("rocket", {}).get("name"),
        }, sort_keys=True)
        # The configured Claude gateway rejects temperature=0 unless its
        # thinking mode is enabled, so omit the parameter and constrain prose
        # through the prompt plus numeric validation.
        text = call_model(prompt, system=system, max_tokens=4000, nonce=f"report-{kind}")
        if validate_llm_numbers(text, facts):
            return text.strip(), False
        retry = call_model(
            json.dumps({
                "facts": facts,
                "validation_error": "Use no numbers except these facts.",
                "offending_numbers": _unsupported_numbers(text, facts),
                "previous": text,
            }),
            system=system,
            max_tokens=4000,
            nonce=f"report-{kind}-retry",
        )
        if validate_llm_numbers(retry, facts):
            return retry.strip(), False
    except Exception:
        pass
    return template, True


def _burn_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    agent = _agent(result)
    rows = []
    time_s = 0.0
    stages = result.get("rocket", {}).get("stages", [])
    for burn in agent.get("ascent", {}).get("burn_table", []):
        stage_num = burn.get("stage")
        stage = stages[stage_num - 1] if isinstance(stage_num, int) and stage_num <= len(stages) else {}
        prop = max(0.0, burn.get("m0_kg", 0) - burn.get("mf_kg", 0))
        thrust = (stage.get("thrust_sl_n", {}).get("value")
                  if isinstance(stage.get("thrust_sl_n"), dict) else None)
        isp = burn.get("isp_used_s")
        duration = None
        if thrust and isp:
            duration = prop / (thrust / (isp * 9.80665))
        rows.append({"stage": stage_num, "name": f"Stage {stage_num} ascent", "start": time_s,
                     "duration": duration, "dv": burn.get("dv_ms"), "prop": prop,
                     "before": burn.get("m0_kg"), "after": burn.get("mf_kg")})
        time_s += duration or 0
    transfer = agent.get("transfer", {})
    for burn in transfer.get("burns", []):
        rows.append({"stage": "transfer", "name": burn.get("name", "transfer burn"), "start": time_s,
                     "duration": None, "dv": burn.get("dv_ms"), "prop": None, "before": None, "after": None})
    return rows


def _plot_ascent(agent: dict[str, Any], path: Path) -> bool:
    ascent = agent.get("ascent", {})
    samples = ascent.get("trajectory_samples") or ascent.get("trajectory")
    if isinstance(samples, dict):
        samples = [
            {"time_s": time, "altitude_km": altitude, "velocity_ms": velocity}
            for time, altitude, velocity in zip(
                samples.get("time_s", samples.get("times_s", [])),
                samples.get("altitude_km", samples.get("altitude_km", [])),
                samples.get("velocity_ms", samples.get("velocity_ms", [])),
            )
        ]
    if not samples:
        return False
    time = [s.get("time_s") for s in samples if s.get("time_s") is not None]
    altitude = [s.get("altitude_km") for s in samples if s.get("altitude_km") is not None]
    velocity = [s.get("velocity_ms") for s in samples if s.get("velocity_ms") is not None]
    if not time or len(time) != len(altitude) or len(time) != len(velocity):
        return False
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(time, altitude, label="Altitude (km)")
    for sample in samples:
        if sample.get("stage_separation") or sample.get("event") == "stage_separation":
            ax.axvline(sample["time_s"], color="0.4", linestyle="--", linewidth=0.8)
    ax.set(xlabel="Time (s)", ylabel="Altitude (km)", title="Ascent profile")
    right = ax.twinx()
    right.plot(time, velocity, color="tab:orange", label="Velocity (m/s)")
    right.set_ylabel("Velocity (m/s)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return True


def _plot_transfer(agent: dict[str, Any], path: Path) -> bool:
    transfer = agent.get("transfer", {})
    if transfer.get("status") != "ok" or transfer.get("destination") in {"LEO", "ISS"}:
        return False
    r1 = (transfer.get("parking_altitude_km", 200) + 6378.137)
    r2 = 384400 if transfer.get("destination") in {"TLI", "Moon"} else None
    if r2 is None:
        return False
    theta = np.linspace(0, np.pi, 300)
    a = (r1 + r2) / 2
    e = (r2 - r1) / (r2 + r1)
    radius = a * (1 - e * e) / (1 + e * np.cos(theta))
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot(radius * np.cos(theta), radius * np.sin(theta), label="Transfer ellipse")
    ax.scatter([0], [0], label="Earth")
    moon = plt.Circle((0, 0), r2, fill=False, linestyle="--", label="Moon orbit")
    ax.add_patch(moon)
    ax.set_aspect("equal", adjustable="box")
    ax.set(xlabel="Distance (km)", ylabel="Distance (km)", title=f"{transfer.get('destination')} transfer trajectory")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return True


def _plot_propellant(result: dict[str, Any], path: Path) -> bool:
    stages = result.get("rocket", {}).get("stages", [])
    if not stages:
        return False
    used = {row["stage"]: row["prop"] or 0 for row in _burn_rows(result) if isinstance(row["stage"], int)}
    available = [stage.get("propellant_mass_kg", {}).get("value") for stage in stages]
    if any(value is None for value in available):
        return False
    x = np.arange(len(stages))
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(x - 0.2, available, 0.4, label="Available")
    ax.bar(x + 0.2, [used.get(i + 1, 0) for i in x], 0.4, label="Used")
    ax.set(xlabel="Stage", ylabel="Propellant (kg)", title="Propellant budget")
    ax.set_xticks(x, [f"Stage {i + 1}" for i in x])
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return True


def _plot_dv(agent: dict[str, Any], path: Path) -> bool:
    ascent, transfer = agent.get("ascent", {}), agent.get("transfer", {})
    if ascent.get("dv_needed_ms") is None or ascent.get("dv_total_ms") is None:
        return False
    labels = ["Ascent", "Transfer"]
    required = [ascent.get("dv_needed_ms", 0), transfer.get("dv_total_ms", 0)]
    available = [ascent.get("dv_total_ms", 0), transfer.get("dv_total_ms", 0)]
    x = np.arange(2)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(x - 0.2, required, 0.4, label="Required")
    ax.bar(x + 0.2, available, 0.4, label="Available")
    ax.set(xlabel="Mission phase", ylabel="Delta-v (m/s)", title="Delta-v budget")
    ax.set_xticks(x, labels)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return True


def _markdown(result: dict[str, Any], out_dir: Path, use_llm: bool) -> str:
    agent, facts = _agent(result), _facts(result)
    verdict_text, verdict_template = _prose(result, facts, "verdict", use_llm)
    recommendation, recommendation_template = _prose(result, facts, "recommendation", use_llm)
    request = result.get("request", {})
    rows = _burn_rows(result)
    links = []
    for name, function in (("ascent.png", lambda p: _plot_ascent(agent, p)),
                           ("transfer.png", lambda p: _plot_transfer(agent, p)),
                           ("propellant.png", lambda p: _plot_propellant(result, p)),
                           ("delta_v.png", lambda p: _plot_dv(agent, p))):
        if function(out_dir / name):
            links.append(f"![{name}]({name})")
    lines = [
        "# Mission report", "",
        "## Verdict", f"**{_verdict(agent)}**", verdict_text,
        f"Request: {request.get('payload_kg', facts.get('requested_payload_kg'))} kg to {request.get('destination', agent.get('transfer', {}).get('destination', 'unknown'))} using {result.get('rocket', {}).get('name', 'unknown')}.", "",
        "## Headline numbers",
        f"- Payload requested: {_fmt(facts.get('requested_payload_kg'), ' kg')}",
        f"- Maximum payload that closes the budget: {_fmt(facts.get('max_payload_kg'), ' kg')}",
        f"- Stock rocket maximum payload (zero added propellant): {_fmt(facts.get('ceiling_kg_stock'), ' kg')}",
        f"- Shortfall: {_fmt(facts.get('shortfall_kg'), ' kg')} ({_fmt(facts.get('shortfall_pct'), '%')})",
        f"- Propellant margin: {_fmt(facts.get('propellant_margin_kg'), ' kg')} ({_fmt(facts.get('propellant_margin_pct'), '%')})",
        f"- Delta-v required vs. available: {_fmt(facts.get('required_delta_v_ms'), ' m/s')} vs. {_fmt(facts.get('available_delta_v_ms'), ' m/s')}", "",
        "## Burn table",
        "| Stage | Burn | Start (s) | Duration (s) | Delta-v (m/s) | Propellant (kg) | Mass before (kg) | Mass after (kg) |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    lines += [f"| {r['stage']} | {r['name']} | {_fmt(r['start'])} | {_fmt(r['duration'])} | {_fmt(r['dv'])} | {_fmt(r['prop'])} | {_fmt(r['before'])} | {_fmt(r['after'])} |" for r in rows] or ["| — | No burn data | — | — | — | — | — | — |"]
    lines += ["", "## Plots"] + (links or ["No trajectory or budget plot data was available."])
    revisions = [h for h in agent.get("history", []) if h.get("event") == "revision"]
    if revisions:
        lines += ["", "## Revision history", "| Change | Why | Outcome |", "|---|---|---|"]
        lines += [f"| {json.dumps(h.get('change', {}), sort_keys=True)} | agent revision | {h.get('revision', {}).get('status', 'unknown')} |" for h in revisions]
    lines += ["", "## Recommendation", recommendation]
    lines += ["", "## Assumptions and provenance"]
    req_source = request.get("payload_source_quote")
    lines.append(f"- Request payload: {_fmt(request.get('payload_kg'), ' kg')} ({'PUBLISHED' if req_source else 'ESTIMATED'}); source: {req_source or 'not supplied'}")
    if request.get("payload_derived"):
        lines.append("- WARNING: Payload was derived or flagged as ambiguous; verify the arithmetic and source quantity.")
    if request.get("target_altitude_km") is not None:
        lines.append(f"- Target altitude: {_fmt(request['target_altitude_km'], ' km')} (PUBLISHED from request).")
    if result.get("rocket", {}).get("variant"):
        lines.append(f"- Rocket variant: {result['rocket']['variant']} (PUBLISHED from parsed specification).")
    else:
        lines.append("- Rocket variant: ESTIMATED/UNSPECIFIED; no variant was supplied.")
    if result.get("rocket", {}).get("published_reference"):
        lines.append(f"- Published reference fields: {json.dumps(result['rocket']['published_reference'], sort_keys=True)}")
    for index, stage in enumerate(result.get("rocket", {}).get("stages", []), 1):
        for field, sourced in stage.items():
            if isinstance(sourced, dict) and sourced.get("value") is not None:
                origin = "PUBLISHED" if sourced.get("source_quote") else "ESTIMATED"
                lines.append(f"- Stage {index} `{field}`: {_fmt(sourced['value'])} ({origin}); source: {sourced.get('source_quote') or 'not supplied'}")
    lines.append(f"- Model assumptions: {agent.get('ascent', {}).get('assumptions', {})}; {agent.get('transfer', {}).get('assumptions', 'not supplied')}.")
    return "\n".join(lines) + "\n"


def generate_report(result: dict[str, Any], out_dir: str | Path) -> Path:
    """Write ``report.md`` and any available PNG plots, returning its path."""
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "report.md"
    report_path.write_text(_markdown(result, output, use_llm=True), encoding="utf-8")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_json", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args(argv)
    result = json.loads(args.result_json.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.md").write_text(_markdown(result, args.out, not args.no_llm), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
