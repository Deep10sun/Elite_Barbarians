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
    assert (tmp_path / "report" / "report.md").exists()


def test_missing_plot_data_does_not_crash(tmp_path):
    report_path = generate_report(_result(), tmp_path / "report")
    text = report_path.read_text()
    assert "No trajectory or budget plot data" not in text
    assert "Ascent profile" not in text
