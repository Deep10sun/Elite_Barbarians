# Elite Barbarians

**Team:** Deep Patel, Srikar Guntaka

Elite Barbarians is a GenAI-assisted rocket mission-planning project. The
long-term goal is to determine whether a rocket can deliver a payload to a
destination by combining ascent performance, orbital transfers, propellant
budgets, and trajectory constraints.

## Project vision

Mission planners repeatedly adjust payloads, staging, and trajectories when a
proposed mission is infeasible. An LLM agent can coordinate this process by
interpreting a mission request, calling physics tools for accurate
calculations, identifying constraints, evaluating tradeoffs, and refining the
mission plan.

The planned end-to-end workflow is:

```text
Mission request + rocket specification
  -> LLM parser
  -> ascent simulator
  -> orbit check
  -> transfer calculator and propagator
  -> propellant and arrival checks
  -> mission revision
  -> report with verdict, plots, burn table, margins, and recommendation
```

## Current implementation

The project currently implements the first part of this workflow: extracting
and validating mission and rocket information.

The current pipeline:

1. Parses a plain-English request into a payload mass and destination.
2. Parses a rocket specification document into structured stage properties.
3. Converts source values to kilograms, seconds, and newtons while retaining
   original units and exact source quotes.
4. Reports missing physics inputs and ambiguities.

The current prototype does **not** yet simulate ascent, calculate orbital
transfers, propagate trajectories, evaluate feasibility, generate plots, or
recommend mission changes. Those capabilities are planned next.

## Project layout

```text
src/
  llm.py          TAMU AI API client and JSON response handling
  parser.py       Mission request parsing and mission assembly
  schema.py       Pydantic data models
  spec_parser.py  Rocket document extraction
  run_mission.py  Command-line entry point
rockets/
  falcon.txt      Example rocket specification document
tests/
  fixtures/       Test input fixtures
example.env       Template for required environment variables
requirements.txt  Python dependencies
demo.ipynb        Interactive demonstration notebook
```

## Requirements

- Python 3.10 or newer
- A TAMU AI API key

Install the dependencies from the project directory:

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root. Do not commit this file.

```dotenv
TAMU_API_KEY=your_api_key_here
```

The API endpoint defaults to `https://chat-api.tamu.ai`. To use another
compatible endpoint, set `TAMUS_AI_CHAT_API_ENDPOINT` in `.env`.

## Rocket specification format

Rocket documents should provide stage-level dry mass, propellant mass, specific
impulse, and thrust. Sea-level and vacuum values should be labeled separately.
Values not present in the document remain `null`; the parser does not fill gaps
from outside knowledge. Payload capacity belongs to the published reference
section and is not used as a stage property.

The included sample document is [rockets/falcon.txt](rockets/falcon.txt).
The current parser reads the specification as document text and produces a
validated structured object. The planned agent interface will support a JSON
rocket specification directly.

## Output

The command prints an indented JSON `Mission` object containing:

- `request`: normalized payload and destination information
- `rocket`: the extracted rocket name, stages, source values, and references
- `missing_fields`: inputs still required by downstream physics tools
- `ambiguities`: unclear or conflicting information from the request or source

## Planned capabilities

- Ascent simulation and orbit-reached checks
- Transfer calculations and trajectory propagation
- Propellant-budget and arrival checks
- Automatic revision of payload, staging, or mission profile
- Feasibility verdicts with burn tables, trajectory plots, propellant margins,
  and recommendations
- ISS and Mars missions as stretch goals after the Moon path

## Evaluation plan

The system will be tested with published and invented rocket specifications,
including Falcon 9, Saturn V, and Electron. Results will be compared against
an LLM without tools and a fixed rule-based calculator.

- **Known-feasible:** payload estimates should match published capacities
  within approximately 15–20%.
- **Borderline:** the system should find a maximum payload that closes the
  mission budget.
- **Impossible:** the system should identify infeasibility and quantify the
  shortfall.

Physics calculations must be validated by simulators and deterministic tools
so the model cannot claim success using unsupported arithmetic or fall into a
self-confirming reasoning loop.

## Run

From the project root:

```bash
python src/run_mission.py
```

or you can add a specific request:

```bash
python src/run_mission.py "Can the Falcon1 Rocket get to the moon with a 1000kg payload?"
```

## Gradio demo

To show the first step in a browser, install the dependencies and start the
Gradio wrapper:

```bash
python -m pip install -r requirements.txt
python src/gradio_app.py
```

Open the local URL printed by Gradio. Enter a mission request, upload
`rockets/falcon.txt` (or paste a specification), and click **Run first step**.
The parsed input and output are displayed in the browser so the page can be
captured as an image for a demo or report.
