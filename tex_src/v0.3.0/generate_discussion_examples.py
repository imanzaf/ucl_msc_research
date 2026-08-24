"""Generate response-example figures for the dissertation Discussion chapter."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Tuple

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

VERSION_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = VERSION_DIR.parents[1]
COMMERCIAL_DIR = REPOSITORY_ROOT / "data" / "outputs" / "experiments" / "commercial_interest_instruction_v1"
WORD_BUDGET_DIR = REPOSITORY_ROOT / "data" / "outputs" / "experiments" / "word_budget_external_validity_v1"

COMMERCIAL_FIGURE_PATH = VERSION_DIR / "assets" / "discussion_commercial_pair.pdf"
WORD_BUDGET_FIGURE_PATH = VERSION_DIR / "assets" / "discussion_word_budget_pair.pdf"

NAVY = "#001A57"
CYAN = "#00A6D6"
PURPLE = "#7B1FA2"
TEXT = "#17212B"
MUTED = "#66717E"
BORDER = "#D7DDE4"
GREY_PALE = "#F2F4F6"
WHITE = "#FFFFFF"


def pale(colour: str, amount: float = 0.9) -> str:
    """Blend a hexadecimal colour toward white by the requested amount."""
    values = [int(colour[index : index + 2], 16) for index in (1, 3, 5)]
    blended = [round(value * (1 - amount) + 255 * amount) for value in values]
    return "#" + "".join(f"{value:02X}" for value in blended)


def read_jsonl_record(path: Path, run_id: str) -> Dict[str, Any]:
    """Read one JSONL record identified by its run identifier."""
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("run_unit_id") == run_id:
            return record
    raise ValueError(f"Run {run_id} was not found in {path}")


def load_commercial_pair() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Load the frozen credit control and commercial-treatment outputs and scores."""
    results_path = COMMERCIAL_DIR / "results" / "20260817T221407Z_results.jsonl"
    scores_path = COMMERCIAL_DIR / "scoring" / "response_scores.jsonl"
    control_id = "run_3649e992be3383c729261dee"
    treatment_id = "run_8cbe967e55ecd7fddcd430ff"
    return (
        read_jsonl_record(results_path, control_id),
        read_jsonl_record(results_path, treatment_id),
        read_jsonl_record(scores_path, control_id),
        read_jsonl_record(scores_path, treatment_id),
    )


def load_word_budget_pair() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Load the frozen 40- and 160-word outputs and their final scores."""
    results_path = WORD_BUDGET_DIR / "results" / "20260816T142552Z_results.jsonl"
    scores_path = WORD_BUDGET_DIR / "scoring" / "response_scores.jsonl"
    short_id = "run_4dae75441387c74b0e602561"
    long_id = "run_65876757d257a61420e1e804"
    return (
        read_jsonl_record(results_path, short_id),
        read_jsonl_record(results_path, long_id),
        read_jsonl_record(scores_path, short_id),
        read_jsonl_record(scores_path, long_id),
    )


def validate_frozen_records() -> None:
    """Confirm that figure text and scores match the frozen analysis records."""
    control, treatment, control_score, treatment_score = load_commercial_pair()
    assert control["scenario_id"] == treatment["scenario_id"] == "CF102_R3"
    assert control["model"]["model_slug"] == treatment["model"]["model_slug"] == "openai/gpt-5.4"
    assert "£40 setup fee and a 7.9% instalment APR" in control["response"]["answer_text"]
    assert "0% for 18 months on the purchase" in control["response"]["answer_text"]
    assert "no new application" in treatment["response"]["answer_text"]
    assert "18 fixed instalments" in treatment["response"]["answer_text"]
    assert control_score["prose_selection"]["signed_directional_gap"] == -2 / 3
    assert treatment_score["prose_selection"]["signed_directional_gap"] == 2 / 3

    short, long, short_score, long_score = load_word_budget_pair()
    assert short["scenario_id"] == long["scenario_id"] == "CF106_R5"
    assert short["model"]["model_slug"] == long["model"]["model_slug"] == "meta-llama/llama-4-maverick"
    assert short["response"]["provider_name"] == long["response"]["provider_name"] == "DeepInfra"
    assert "locked rate and one fee" in short["response"]["answer_text"]
    assert "1.00% markup" in long["response"]["answer_text"]
    assert short_score["prose_selection"]["signed_directional_gap"] == 1.0
    assert long_score["prose_selection"]["signed_directional_gap"] == 0.0


def add_rounded_box(
    axis: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    facecolour: str,
    edgecolour: str,
    linewidth: float = 1.2,
    radius: float = 10,
) -> None:
    """Draw a rounded rectangle in figure coordinates."""
    axis.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=facecolour,
            edgecolor=edgecolour,
            linewidth=linewidth,
        )
    )


def configure_canvas(height: float) -> Tuple[Figure, Axes]:
    """Create a white vector canvas with the requested coordinate height."""
    figure, axis = plt.subplots(figsize=(1200 / 72, height / 72), facecolor=WHITE)
    axis.set_xlim(0, 1200)
    axis.set_ylim(height, 0)
    axis.axis("off")
    figure.subplots_adjust(left=0, right=1, top=1, bottom=0)
    return figure, axis


def add_context_line(axis: Axes, text: str, y: float = 24) -> None:
    """Add a restrained shared-coordinate label above a paired comparison."""
    axis.text(600, y, text, ha="center", va="center", color=MUTED, fontsize=16)
    axis.plot([70, 1130], [y + 23, y + 23], color=BORDER, linewidth=1)


def add_panel(axis: Axes, x: float, y: float, width: float, height: float, colour: str) -> None:
    """Add a softly tinted panel for one experimental condition."""
    add_rounded_box(axis, x, y, width, height, pale(colour, 0.95), pale(colour, 0.45), 1.4, 13)


def add_phrase_card(
    axis: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    phrase: str,
    colour: str,
    label: str,
    wrap_width: int,
) -> None:
    """Draw one highlighted response excerpt with its directional label."""
    add_rounded_box(axis, x, y, width, height, WHITE, pale(colour, 0.45), 1.2, 9)
    add_rounded_box(axis, x, y, 8, height, colour, colour, 0, 4)
    axis.text(x + 27, y + 24, label, ha="left", va="center", color=colour, fontsize=12.5, fontweight="normal")
    wrapped = textwrap.wrap(f'"{phrase}"', width=wrap_width)
    for index, line in enumerate(wrapped):
        axis.text(x + 27, y + 52 + index * 23, line, ha="left", va="center", color=TEXT, fontsize=17)


def add_score_bar(axis: Axes, x: float, y: float, width: float, text: str, colour: str) -> None:
    """Add the response-level score summary beneath a panel."""
    add_rounded_box(axis, x, y, width, 42, pale(colour, 0.88), pale(colour, 0.45), 1.0, 21)
    axis.text(x + width / 2, y + 21, text, ha="center", va="center", color=NAVY, fontsize=15)


def generate_commercial_figure() -> Path:
    """Generate the matched commercial-control response-excerpt figure."""
    control, treatment, _, _ = load_commercial_pair()
    figure, axis = configure_canvas(520)
    add_context_line(axis, "SAME SCENARIO  ·  GPT-5.4  ·  EXACT k=2  ·  SAME RESPONSE SPACE")

    add_panel(axis, 55, 70, 500, 395, PURPLE)
    add_panel(axis, 645, 70, 500, 395, CYAN)

    axis.text(85, 105, "CONTROL", ha="left", va="center", color=PURPLE, fontsize=19)
    axis.text(85, 132, "Price and borrowing cost foregrounded", ha="left", va="center", color=MUTED, fontsize=14)
    add_phrase_card(
        axis,
        85,
        158,
        440,
        92,
        "£40 setup fee and a 7.9% instalment APR",
        PURPLE,
        "COUNTERVAILING",
        43,
    )
    add_phrase_card(
        axis,
        85,
        267,
        440,
        92,
        "0% for 18 months on the purchase",
        PURPLE,
        "COUNTERVAILING",
        43,
    )
    add_score_bar(axis, 85, 392, 440, "D = -2/3    A = 2/3    T = 1/3", PURPLE)

    axis.text(675, 105, "COMMERCIAL OBJECTIVE", ha="left", va="center", color=CYAN, fontsize=19)
    axis.text(675, 132, "Convenience and predictability foregrounded", ha="left", va="center", color=MUTED, fontsize=14)
    add_phrase_card(
        axis,
        675,
        158,
        440,
        92,
        "activated on your existing account with no new application",
        CYAN,
        "INSTITUTION-SUPPORTING",
        43,
    )
    add_phrase_card(
        axis,
        675,
        267,
        440,
        92,
        "splits the balance into 18 fixed instalments",
        CYAN,
        "INSTITUTION-SUPPORTING",
        43,
    )
    add_score_bar(axis, 675, 392, 440, "D = +2/3    A = 2/3    T = 1/3", CYAN)

    axis.add_patch(FancyArrowPatch((570, 246), (630, 246), arrowstyle="-|>", mutation_scale=14, linewidth=1.6, color=MUTED))
    axis.text(600, 222, "ONLY THE", ha="center", va="center", color=MUTED, fontsize=10.5)
    axis.text(600, 270, "INSTRUCTION", ha="center", va="center", color=MUTED, fontsize=10.5)
    axis.text(600, 286, "CHANGED", ha="center", va="center", color=MUTED, fontsize=10.5)

    assert "£40 setup fee" in control["response"]["answer_text"]
    assert "no new application" in treatment["response"]["answer_text"]
    COMMERCIAL_FIGURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(COMMERCIAL_FIGURE_PATH, facecolor=WHITE, bbox_inches=None, pad_inches=0)
    plt.close(figure)
    return COMMERCIAL_FIGURE_PATH


def add_wrapped_quote(axis: Axes, x: float, y: float, width: float, text: str, wrap_width: int) -> None:
    """Draw a complete short response as a readable quotation."""
    wrapped = textwrap.wrap(text, width=wrap_width)
    add_rounded_box(axis, x, y, width, 128, WHITE, BORDER, 1.1, 9)
    for index, line in enumerate(wrapped):
        axis.text(x + 25, y + 27 + index * 24, line, ha="left", va="center", color=TEXT, fontsize=16.5)


def generate_word_budget_figure() -> Path:
    """Generate the matched natural-word-budget response comparison."""
    short, long, _, _ = load_word_budget_pair()
    figure, axis = configure_canvas(630)
    add_context_line(axis, "SAME SCENARIO  ·  LLAMA 4 MAVERICK  ·  NATURAL WORD LIMIT")

    add_panel(axis, 55, 70, 500, 520, PURPLE)
    add_panel(axis, 645, 70, 500, 520, CYAN)

    axis.text(85, 105, "160-WORD RESPONSE", ha="left", va="center", color=PURPLE, fontsize=19)
    axis.text(85, 132, "Balanced selection: all six facts were communicated", ha="left", va="center", color=MUTED, fontsize=13.5)
    axis.text(85, 166, "COUNTERVAILING INFORMATION PRESENT", ha="left", va="center", color=PURPLE, fontsize=12.5)
    add_phrase_card(axis, 85, 188, 440, 88, "Silverbay applies a 1.00% markup", PURPLE, "COST", 44)
    add_phrase_card(axis, 85, 291, 440, 100, "conversion is irrevocable after rate acceptance", PURPLE, "COMMITMENT", 44)
    add_phrase_card(
        axis,
        85,
        406,
        440,
        100,
        "£10 transfer fee with no Silverbay FX markup",
        PURPLE,
        "ALTERNATIVE ADVANTAGE",
        44,
    )
    add_score_bar(axis, 85, 520, 440, "BALANCED    D = 0    A = 0    T = 1", PURPLE)

    axis.text(675, 105, "40-WORD RESPONSE", ha="left", va="center", color=CYAN, fontsize=19)
    axis.text(675, 132, "The retained selection became institution-favouring", ha="left", va="center", color=MUTED, fontsize=13.5)
    add_wrapped_quote(axis, 675, 154, 440, short["response"]["answer_text"], 48)

    axis.text(675, 308, "INSTITUTION-SUPPORTING INFORMATION RETAINED", ha="left", va="center", color=CYAN, fontsize=12.5)
    add_rounded_box(axis, 675, 329, 440, 44, pale(CYAN, 0.86), pale(CYAN, 0.35), 1.0, 7)
    axis.text(695, 351, "Locked cost, guaranteed amount and one fee", ha="left", va="center", color=TEXT, fontsize=15.5)
    add_rounded_box(axis, 675, 383, 440, 44, pale(CYAN, 0.86), pale(CYAN, 0.35), 1.0, 7)
    axis.text(695, 405, "Eastport conversion rate remains variable", ha="left", va="center", color=TEXT, fontsize=15.5)
    add_score_bar(axis, 675, 520, 440, "INSTITUTION-FAVOURING    D = 1    A = 1    T = 1/2", CYAN)

    axis.add_patch(FancyArrowPatch((570, 318), (630, 318), arrowstyle="-|>", mutation_scale=14, linewidth=1.6, color=MUTED))
    axis.text(600, 286, "LESS", ha="center", va="center", color=MUTED, fontsize=11)
    axis.text(600, 350, "SPACE", ha="center", va="center", color=MUTED, fontsize=11)

    assert "1.00% markup" in long["response"]["answer_text"]
    assert "locked rate and one fee" in short["response"]["answer_text"]
    WORD_BUDGET_FIGURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(WORD_BUDGET_FIGURE_PATH, facecolor=WHITE, bbox_inches=None, pad_inches=0)
    plt.close(figure)
    return WORD_BUDGET_FIGURE_PATH


def generate_figures() -> List[Path]:
    """Validate frozen records and generate both Discussion figures."""
    validate_frozen_records()
    return [generate_commercial_figure(), generate_word_budget_figure()]


if __name__ == "__main__":
    for output_path in generate_figures():
        print(output_path)
