import json
from pathlib import Path

import gradio as gr

from parser import build_mission


DEFAULT_REQUEST = "Can this rocket put a 5,000 kg payload on a trans-lunar trajectory?"
DEFAULT_SPEC_PATH = Path(__file__).resolve().parents[1] / "rockets" / "falcon.txt"


def run_first_step(
    request_text: str,
    spec_file: str | None,
    spec_text: str,
    vehicle_hint: str,
) -> dict:
    if not request_text.strip():
        raise gr.Error("Enter a mission request.")

    if spec_file:
        spec_path = Path(spec_file)
        document = spec_path.read_text(encoding="utf-8")
    elif spec_text.strip():
        document = spec_text
    else:
        raise gr.Error("Upload a rocket specification or paste its text.")

    mission = build_mission(
        request_text.strip(),
        document,
        vehicle_hint=vehicle_hint.strip(),
    )
    return json.loads(mission.model_dump_json())


def create_demo() -> gr.Blocks:
    with gr.Blocks(title="Rocket Mission Parser") as demo:
        gr.Markdown(
            "# Rocket mission parser\n"
            "The first pipeline step extracts and validates mission and rocket "
            "information. It does not run physics simulations yet."
        )

        with gr.Row():
            with gr.Column():
                request = gr.Textbox(
                    label="Mission request",
                    value=DEFAULT_REQUEST,
                    lines=3,
                )
                vehicle = gr.Textbox(label="Vehicle hint", value="Falcon")
                spec_file = gr.File(
                    label="Rocket specification (.txt)",
                    file_types=[".txt"],
                    type="filepath",
                )
                spec_text = gr.Textbox(
                    label="Or paste rocket specification",
                    lines=12,
                    placeholder="Paste the specification here if you do not upload a file.",
                )
                run = gr.Button("Run first step", variant="primary")

            with gr.Column():
                output = gr.JSON(label="Parsed mission output")

        run.click(
            fn=run_first_step,
            inputs=[request, spec_file, spec_text, vehicle],
            outputs=output,
        )

    return demo


if __name__ == "__main__":
    create_demo().launch()
