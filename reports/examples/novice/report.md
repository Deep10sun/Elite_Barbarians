# Mission report

## Verdict
**NOT FEASIBLE AS REQUESTED**
The mission is infeasible as requested, with the vehicle's maximum payload of 5624 kg falling 85094.474 kg (93.8%) short of the requested 90718.474 kg.
Request: 90718.474 kg to Moon using Falcon 9.

## Headline numbers
- Payload requested: 90,718.5 kg
- Maximum payload that closes the budget: 5,624 kg
- Stock rocket maximum payload (zero added propellant): 4,590 kg
- Shortfall: 85,094.5 kg (93.8%)
- Propellant margin: 0 kg (0%)
- Delta-v required vs. available: 12,587.9 m/s vs. 12,588 m/s


## Benchmark comparison

| Method | Verdict correct | Mean ceiling error | Mean shortfall error | Missing fields correct | Errors |
|---|---:|---:|---:|---:|---:|
| full_agent | 1/1 | 0.0 kg (n=1) | 1034.0 kg (n=1) | 0/0 | 0 |
| llm_only | 1/1 | 16810.0 kg (n=1) | 15776.0 kg (n=1) | 0/0 | 0 |
| rule_based | 1/1 | 0.0 kg (n=1) | 1034.0 kg (n=1) | 0/0 | 0 |

## Burn table
| Stage | Burn / coast | Start (s) | Duration / travel (s) | Delta-v (m/s) | Propellant (kg) | Mass before (kg) | Mass after (kg) |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | Stage 1 ascent | 0 | 174.5 | 4,166.3 | 455,055 | 598,581 | 143,526 |
| 2 | Stage 2 ascent | 174.5 | 370.7 | 8,421.7 | 106,570 | 116,442 | 9,872 |
| transfer | trans-lunar injection | 545.3 | 430,095.3 | 3,131.3 | — | — | — |

For ascent rows, duration is the modeled powered-burn time. For the transfer row, duration is the modeled coast/travel time; propellant and mass fields are not supplied by the transfer model.

## Plots
![transfer.png](transfer.png)
![propellant.png](propellant.png)
![delta_v.png](delta_v.png)

## Revision history
| Change | Why | Outcome |
|---|---|---|
| {"add_propellant_kg": 59355.0, "stage": 1} | agent revision | ok |
| {"add_propellant_kg": 13900.5, "stage": 2} | agent revision | ok |
| {"payload_kg": 5624} | agent revision | ok |

## Recommendation
Reduce the payload to about 5,624 kg or increase available propellant; the requested 90,718.5 kg exceeds the transfer-aware ceiling.

## Assumptions and provenance
- Request payload: 90,718.5 kg (PUBLISHED); source: 200,000 pounds
- WARNING: Payload was derived or flagged as ambiguous; verify the arithmetic and source quantity.
- Rocket variant: ESTIMATED/UNSPECIFIED; no variant was supplied.
- Published reference fields: {"leo_payload_kg": 22800}
- Stage 1 `dry_mass_kg`: 25,600 (PUBLISHED); source: Empty mass	25,600 kg / 56,423 lb
- Stage 1 `propellant_mass_kg`: 395,700 (PUBLISHED); source: Propellant mass	395,700 kg/ 872,369 lb
- Stage 1 `isp_vac_s`: 312 (PUBLISHED); source: Specific Impulse (vacuum sec)	312 sec.
- Stage 1 `isp_sl_s`: 283 (PUBLISHED); source: Specific Impulse (sea-level)	283 sec.
- Stage 1 `thrust_vac_n`: 8,227,000 (PUBLISHED); source: Thrust in vacuum	8,227 kN / 1,849,500 lbf
- Stage 1 `thrust_sl_n`: 7,607,000 (PUBLISHED); source: Thrust at sea Level	7,607 kN / 1,710,000 lbf
- Stage 2 `dry_mass_kg`: 3,900 (PUBLISHED); source: Empty mass	3,900 kg / 8,598 lb
- Stage 2 `propellant_mass_kg`: 92,670 (PUBLISHED); source: Propellant mass	92,670 kg / 204,302 lb
- Stage 2 `isp_vac_s`: 348 (PUBLISHED); source: Specific Impulse (vacuum)	348 sec
- Stage 2 `thrust_vac_n`: 981,000 (PUBLISHED); source: Thrust	981 kN / 220,500 lbf
- Model assumptions: {'losses_ms': 1500.0, 'v_target_ms': 7800.0, 's1_isp_mode': 'average', 'model': 'rocket equation minus fixed loss budget'}; Hohmann-to-lunar-distance estimate using Earth gravity only; TLI excludes lunar orbit insertion; lunar capture is not modeled.


## Novice notes: assumptions and glossary

- **Payload assumption:** 90,718 kg, using 100 kg per person for 30 people. Cabin, life support, supplies, and other mission hardware are not included.
- **Destination assumption:** the Moon-bound request is modeled as a transfer from the default 200 km parking orbit. It does not model lunar capture, landing, or a return mission.
- **Plain-language result:** the model's payload ceiling is 5,624 kg. Compare it with the requested payload above; this simplified budget check is not proof that people could safely fly.

| Term | Plain-language meaning |
| --- | --- |
| Payload | The mass being carried, excluding rocket stages; cabin and life-support mass would also need to be counted. |
| Parking orbit | A temporary orbit around Earth before the next major burn. |
| TLI | Trans-lunar injection: a burn intended to put a spacecraft on a path toward the Moon. |
| Delta-v | A measure of how much a vehicle can change its velocity; it is a budget, not simply its final speed. |
| Apogee | The highest point of an orbit. This pipeline does not calculate an apogee for this mission. |

The model does not establish human-rating, life-support adequacy, launch licensing, lunar capture, landing, or crew return.
