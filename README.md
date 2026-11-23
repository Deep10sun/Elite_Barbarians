# Elite Barbarians

**Team:** Deep Patel, Srikar Guntaka

Elite Barbarians is a GenAI-assisted rocket mission-planning project. Given a
plain-English mission request and a rocket specification, it parses the inputs,
checks the vehicle with deterministic physics tools, evaluates ascent and
transfer budgets, and returns a feasibility result with an explanation.

The LLM is used to parse requests and suggest bounded revisions. It does not
perform the physics calculations or directly edit a vehicle. The physics,
validation, margin, and payload-ceiling values come from code in `src/`.

## Repository map

```text
src/
  run_mission.py       Main command-line entry point
  gradio_app.py        Browser UI for the parsing step
  report.py            Report and plot generator for saved JSON results
  llm_parser/
    parser.py          Mission/specification parsing and validation
    spec_parser.py     Rocket document extraction
  llm_utils/
    schema.py          Pydantic input/output models
    llm.py             TAMU AI API client
  ascent_loop/
    agent.py           Mission evaluation and revision loop
    physics.py         Ascent calculations and validation
    transfer.py        Destination transfer calculations
    revise.py          Bounded candidate-revision gate
rockets/
  falcon9.txt          Example rocket specification
tests/
  fixtures/            Saved result fixtures
  test_*.py            Unit and report tests
reports/examples/      Example generated reports
demo.ipynb             Interactive demonstration
example.env            Environment-variable template
requirements.txt       Python dependencies
```

Read the repository from the outside in:

1. Start with `src/run_mission.py` to see the command-line inputs and output.
2. Follow `llm_parser/` to see how text becomes a validated `Mission`.
3. Follow `ascent_loop/agent.py` and its `physics.py`, `transfer.py`, and
   `revise.py` helpers to see how candidates are evaluated.
4. Use `src/report.py` to understand how saved results become Markdown and
   plots.
5. Use `tests/` and `reports/examples/` for executable examples of expected
   behavior.

## Requirements and setup

- Python 3.10 or newer
- A TAMU AI API key for mission parsing and the agent loop

From the repository root, create an environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate        # macOS/Linux
python -m pip install -r requirements.txt
```

Create `.env` in the repository root. Do not commit it:

```dotenv
TAMU_API_KEY=your_api_key_here
```

The API endpoint defaults to `https://chat-api.tamu.ai`. For a compatible
endpoint, also set `TAMUS_AI_CHAT_API_ENDPOINT` in `.env`.

## Run a mission from the command line

Run the default example using `rockets/falcon9.txt`:

```bash
python -m src.run_mission
```

Provide a request, a specification path, and the maximum number of agent
iterations as positional arguments:

```bash
python -m src.run_mission \
  "Can this rocket put a 5000 kg payload into LEO?" \
  rockets/falcon9.txt \
  5
```

The arguments are:

```text
python -m src.run_mission [request] [specification_path] [iterations]
```

`request` defaults to the trans-lunar Falcon example, the specification path
defaults to `rockets/falcon9.txt`, and `iterations` defaults to `5`. Run from
the repository root so Python can import `src` and relative paths resolve as
shown.

The command prints an indented JSON result to standard output. Save it when
you want to generate a report:

```bash
python -m src.run_mission \
  "Can this rocket put a 5000 kg payload into LEO?" \
  rockets/falcon9.txt 5 > result.json
```

## Benchmark a saved mission report

Report generation includes a benchmark comparison based on `result.json`, not
the fixed benchmark fixtures:

```bash
python -m src.report result.json --out reports/my-mission/ --no-llm
```

The benchmark section compares `full_agent`, `llm_only`, and `rule_based`
against the saved mission and appends the Markdown table to `report.md`.
Without `--no-llm`, the full-agent and direct-LLM benchmark methods require
`TAMU_API_KEY`. Use `--benchmark-trials 3` to repeat the comparison three
times, or `--no-benchmark` to omit the section.

If parsing cannot find required information, the command prints a JSON error
with `"status": "error"` and a `missing_fields` list, then exits with status 1.
Add the missing payload, destination, or stage properties to the request or
specification and rerun.

## Generate a report

Create a deterministic Markdown report and any available PNG plots from a
saved mission result:

```bash
python -m src.report result.json --out reports/my-mission/ --no-llm
```

The `--no-llm` option is recommended for reproducible local reports. Without
it, the report may ask the TAMU AI gateway to rewrite the verdict and
recommendation; numeric output is validated against the saved facts and falls
back to deterministic text if needed. The output directory can contain:

- `report.md`: verdict, headline numbers, burn table, revision history,
  assumptions, provenance, and recommendation
- `ascent.png`: altitude/velocity profile, when trajectory samples exist
- `transfer.png`: transfer trajectory, when supported by the result
- `propellant.png`: available versus used propellant by stage
- `delta_v.png`: required versus available delta-v

Example reports are in `reports/examples/`.

## Use the browser demo

The Gradio app demonstrates the parsing step. It does not run the full mission
evaluation loop:

```bash
python src/gradio_app.py
```

Open the local URL printed by Gradio. Enter a mission request and either upload
`rockets/falcon9.txt` or paste a rocket specification, then click **Run first
step**.

## Rocket specification format

Rocket documents should provide stage-level:

- dry mass
- propellant mass
- specific impulse
- thrust

Label sea-level and vacuum values separately. Values absent from the document
remain `null`; the parser does not fill gaps from outside knowledge. Published
payload-capacity information belongs in the reference section and is not
treated as a stage property. The parser preserves normalized values, original
units, and source quotes for provenance.

## How to interpret mission JSON

The top-level result normally contains:

| Field | Meaning |
|---|---|
| `request` | Normalized payload, destination, altitude, and source quote |
| `rocket` | Parsed rocket name, variant, stages, references, and source values |
| `missing_fields` | Inputs that are still required; an empty list means none were detected |
| `ambiguities` | Conflicting, vague, derived, or otherwise uncertain input details |
| `agent` | Deterministic evaluations, candidate revisions, facts, and final verdict |

Important nested sections in `agent` are:

- `ascent`: whether the vehicle reaches the modeled parking orbit, delta-v
  required/available, burn table, trajectory samples, and assumptions.
- `transfer`: destination, transfer status, transfer delta-v, burns, and
  propagation assumptions.
- `margin`: combined budget margin and propellant requirement.
- `facts`: the saved numeric facts used to derive the final verdict.
- `history`: every evaluation and revision attempt. A revision with
  `"status": "rejected"` was not applied.

Interpret `agent.facts.verdict` as follows:

| Verdict | Interpretation |
|---|---|
| `feasible` | The requested payload closes the modeled ascent and transfer budgets. |
| `infeasible_as_requested` | The exact request does not close, but the loop found a smaller payload or another bounded change that does. |
| `infeasible` | The modeled mission remains infeasible after the allowed revisions. |

Treat `missing_fields` and `ambiguities` as input-quality warnings, not as
evidence that a mission is feasible. A `feasible` result is only valid for the
stated rocket data, destination model, and assumptions. Check the report's
**Assumptions and provenance** section before using a result as an engineering
claim. `PUBLISHED` values have a source quote; `ESTIMATED` or
`ESTIMATED/UNSPECIFIED` values need verification.

## Test the repository

Run the unit and report tests from the repository root:

```bash
python -m pytest
```

The tests cover unit conversion, parking-altitude handling, verdict logic, and
report generation without requiring a live LLM call.

## Current scope and planned work

The implemented workflow covers parsing, validation, ascent simulation,
destination transfer calculations, propellant and margin checks, bounded
revisions, and report generation. Planned extensions include broader mission
profiles, more vehicle specifications, richer trajectory propagation, and
additional validation against published Falcon 9, Saturn V, and Electron
results.
