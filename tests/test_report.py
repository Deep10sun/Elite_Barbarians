import json

from src.report import generate_report, validate_llm_numbers


def test_number_validator_rejects_hallucinated_number():
    assert validate_llm_numbers("Margin is 1,000 m/s.", {"margin": 1000})
    assert not validate_llm_numbers("Margin is 999 m/s.", {"margin": 1000})


def _result():
    return {
        "request": {"payload_kg": 500, "destination": "LEO"},
        "rocket": {
            "name": "Test rocket",
            "stages": [{
                "dry_mass_kg": {"value": 100, "source_quote": "published"},
                "propellant_mass_kg": {"value": 900, "source_quote": "published"},
                "isp_vac_s": {"value": 300, "source_quote": "published"},
            }],
        },
        "agent": {
            "verdict": "feasible",
            "candidate": {"payload_kg": 500},
            "ascent": {
                "dv_total_ms": 4000, "dv_needed_ms": 3000,
                "burn_table": [{"stage": 1, "m0_kg": 1000, "mf_kg": 100, "dv_ms": 4000}],
            },
            "transfer": {"destination": "LEO", "status": "ok", "dv_total_ms": 0, "burns": []},
            "margin": {"feasible": True, "margin_ms": 1000, "propellant_needed_kg": 0},
            "history": [],
        },
    }


def test_no_llm_cli_path(tmp_path, monkeypatch):
    source = tmp_path / "result.json"
    source.write_text(json.dumps(_result()))
    from src import report
    assert report.main([str(source), "--out", str(tmp_path / "report"), "--no-llm"]) == 0
    report_text = (tmp_path / "report" / "report.md").read_text()
    assert "## Benchmark comparison" in report_text
    assert "| rule_based |" in report_text
    assert "skipped (--no-llm)" in report_text


def test_missing_plot_data_does_not_crash(tmp_path):
    report_path = generate_report(_result(), tmp_path / "report")
    text = report_path.read_text()
    assert "No trajectory or budget plot data" not in text
    assert "Ascent profile" not in text


def test_burn_table_uses_stage2_vacuum_thrust_and_transfer_time(tmp_path):
    result = _result()
    result["request"]["destination"] = "TLI"
    result["rocket"]["stages"] = [{
        "dry_mass_kg": {"value": 100},
        "propellant_mass_kg": {"value": 900},
        "isp_vac_s": {"value": 300},
        "isp_sl_s": {"value": 280},
        "thrust_sl_n": {"value": 1000},
        "thrust_vac_n": {"value": 1000},
    }, {
        "dry_mass_kg": {"value": 100},
        "propellant_mass_kg": {"value": 900},
        "isp_vac_s": {"value": 300},
        "thrust_vac_n": {"value": 1000},
    }]
    result["agent"]["ascent"]["burn_table"].append({
        "stage": 2,
        "m0_kg": 1000,
        "mf_kg": 100,
        "dv_ms": 3000,
        "isp_used_s": 300,
    })
    result["agent"]["transfer"] = {
        "destination": "TLI",
        "status": "ok",
        "dv_total_ms": 3000,
        "time_s": 430095,
        "burns": [{"name": "trans-lunar injection", "dv_ms": 3000}],
    }

    report_path = generate_report(
        result,
        tmp_path / "report",
        use_llm=False,
        include_benchmark=False,
    )
    text = report_path.read_text()
    assert "430,095" in text
    assert "| 2 | Stage 2 ascent" in text
    assert "Duration / travel (s)" in text


def test_rule_based_uses_saved_destination():
    from src.benchmark_methods import rule_based
    from src.llm_utils.schema import Mission

    mission = Mission.model_validate({
        "request": {
            "payload_kg": 500,
            "payload_source_quote": "500 kg",
            "destination": "TLI",
            "vehicle_name": "Test rocket",
        },
        "rocket": {
            "name": "Test rocket",
            "stages": [{
                "dry_mass_kg": {"value": 25600},
                "propellant_mass_kg": {"value": 395700},
                "isp_vac_s": {"value": 312},
                "isp_sl_s": {"value": 283},
            }, {
                "dry_mass_kg": {"value": 3900},
                "propellant_mass_kg": {"value": 92670},
                "isp_vac_s": {"value": 348},
                "isp_sl_s": {"value": 348},
            }],
        },
    })

    leo = mission.model_copy(deep=True)
    leo.request.destination = "LEO"
    tli = rule_based(mission, "destination-test")
    leo_result = rule_based(leo, "leo-test")

    assert tli.payload_ceiling_kg is not None
    assert leo_result.payload_ceiling_kg is not None
    assert tli.payload_ceiling_kg < leo_result.payload_ceiling_kg
