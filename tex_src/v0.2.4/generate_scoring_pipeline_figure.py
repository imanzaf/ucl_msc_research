"""Generate the response-scoring pipeline figure for dissertation review."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Tuple

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Polygon

OUTPUT_PATH = Path(__file__).resolve().parent / "assets" / "scoring_pipeline_diagram.pdf"

NAVY = "#001A57"
BLUE = "#2F8FFF"
CYAN = "#00A6D6"
PURPLE = "#7B1FA2"
ORANGE = "#FF7A2F"
TEXT = "#17212B"
MUTED = "#747D88"
BORDER = "#D9DEE5"
WHITE = "#FFFFFF"


def pale(colour: str, amount: float = 0.9) -> str:
    """Blend one hexadecimal colour toward white by the requested amount."""
    values = [int(colour[index : index + 2], 16) for index in (1, 3, 5)]
    blended = [round(value * (1 - amount) + 255 * amount) for value in values]
    return "#" + "".join(f"{value:02X}" for value in blended)


def add_rounded_box(
    axis: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    facecolour: str,
    edgecolour: str,
    linewidth: float = 1.3,
    radius: float = 8,
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


def add_arrow(axis: Axes, start: Tuple[float, float], end: Tuple[float, float], colour: str = MUTED) -> None:
    """Draw a restrained directional connector between two points."""
    axis.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=12,
            linewidth=1.6,
            color=colour,
        )
    )


def add_document_icon(axis: Axes, x: float, y: float) -> None:
    """Draw the generated-response document icon."""
    axis.add_patch(Circle((x, y), 52, facecolor=pale(BLUE), edgecolor=BLUE, linewidth=1.5))
    axis.plot(
        [x - 25, x + 9, x + 25, x + 25, x - 25, x - 25],
        [y - 31, y - 31, y - 15, y + 33, y + 33, y - 31],
        color=BLUE,
        linewidth=2.5,
        solid_joinstyle="round",
    )
    axis.plot([x + 9, x + 9, x + 25], [y - 31, y - 15, y - 15], color=BLUE, linewidth=2.5)
    for offset, width in ((-3, 30), (10, 36), (23, 25)):
        axis.plot([x - 15, x - 15 + width], [y + offset, y + offset], color=BLUE, linewidth=2.2, solid_capstyle="round")


def add_content_icon(axis: Axes, x: float, y: float) -> None:
    """Draw a proposition-extraction icon for the content judge."""
    axis.add_patch(Circle((x, y), 46, facecolor=pale(CYAN), edgecolor=CYAN, linewidth=1.4))
    add_rounded_box(axis, x - 25, y - 27, 38, 48, WHITE, CYAN, 2.1, 4)
    axis.plot([x - 15, x + 3], [y - 12, y - 12], color=CYAN, linewidth=2, solid_capstyle="round")
    axis.plot([x - 15, x - 2], [y, y], color=CYAN, linewidth=2, solid_capstyle="round")
    axis.add_patch(Circle((x + 13, y + 11), 14, facecolor=WHITE, edgecolor=CYAN, linewidth=2.3))
    axis.plot([x + 23, x + 34], [y + 22, y + 33], color=CYAN, linewidth=2.5, solid_capstyle="round")


def add_presentation_icon(axis: Axes, x: float, y: float) -> None:
    """Draw a speech-analysis icon for the presentation judge."""
    axis.add_patch(Circle((x, y), 46, facecolor=pale(PURPLE), edgecolor=PURPLE, linewidth=1.4))
    add_rounded_box(axis, x - 28, y - 22, 56, 38, WHITE, PURPLE, 2.2, 8)
    axis.add_patch(
        Polygon(
            [(x - 10, y + 15), (x - 17, y + 28), (x + 2, y + 16)],
            closed=True,
            facecolor=WHITE,
            edgecolor=PURPLE,
            linewidth=2.1,
        )
    )
    axis.plot([x - 16, x + 16], [y - 8, y - 8], color=PURPLE, linewidth=2, solid_capstyle="round")
    axis.plot([x - 16, x + 7], [y + 3, y + 3], color=PURPLE, linewidth=2, solid_capstyle="round")


def add_accuracy_icon(axis: Axes, x: float, y: float) -> None:
    """Draw an issue-detection shield icon for the accuracy judge."""
    axis.add_patch(Circle((x, y), 46, facecolor=pale(ORANGE), edgecolor=ORANGE, linewidth=1.4))
    axis.add_patch(
        Polygon(
            [(x, y - 31), (x + 28, y - 20), (x + 22, y + 17), (x, y + 34), (x - 22, y + 17), (x - 28, y - 20)],
            closed=True,
            facecolor=WHITE,
            edgecolor=ORANGE,
            linewidth=2.3,
        )
    )
    axis.plot([x, x], [y - 15, y + 8], color=ORANGE, linewidth=3, solid_capstyle="round")
    axis.add_patch(Circle((x, y + 19), 2.8, facecolor=ORANGE, edgecolor="none"))


def add_judge_label(axis: Axes, y: float, heading: str, details: Sequence[str], colour: str) -> None:
    """Add one judge heading and its concise input description."""
    axis.text(389, y - 10, heading, ha="left", va="center", color=TEXT, fontsize=15)
    for index, detail in enumerate(details):
        axis.text(389, y + 17 + index * 20, detail, ha="left", va="center", color=MUTED, fontsize=11.5)
    axis.plot([389, 560], [y - 28, y - 28], color=pale(colour, 0.55), linewidth=2)


def add_output_card(
    axis: Axes,
    y: float,
    height: float,
    colour: str,
    heading: str,
    lines: Sequence[str],
) -> None:
    """Draw one judge-output card with direct labels."""
    add_rounded_box(axis, 595, y, 575, height, WHITE, pale(colour, 0.3), 1.4, 10)
    add_rounded_box(axis, 595, y, 8, height, colour, colour, 0, 4)
    axis.text(625, y + 27, heading, ha="left", va="center", color=TEXT, fontsize=13.5)
    for index, line in enumerate(lines):
        axis.text(625, y + 55 + index * 23, line, ha="left", va="center", color=MUTED, fontsize=11.5)


def configure_canvas() -> tuple[Figure, Axes]:
    """Create a white vector canvas matching the manuscript figure proportions."""
    figure, axis = plt.subplots(figsize=(1200 / 72, 510 / 72), facecolor=WHITE)
    axis.set_xlim(0, 1200)
    axis.set_ylim(510, 0)
    axis.axis("off")
    figure.subplots_adjust(left=0, right=1, top=1, bottom=0)
    return figure, axis


def generate_figure() -> Path:
    """Generate the redesigned scoring-pipeline preview as a vector PDF."""
    figure, axis = configure_canvas()

    axis.text(600, 27, "ONE RESPONSE  ·  EIGHT INDEPENDENT JUDGE CALLS", ha="center", va="center", color=MUTED, fontsize=13)
    axis.plot([74, 1126], [47, 47], color=BORDER, linewidth=1)

    add_document_icon(axis, 125, 256)
    axis.text(125, 327, "MODEL RESPONSE", ha="center", va="center", color=TEXT, fontsize=15)

    axis.plot([177, 225], [256, 256], color=MUTED, linewidth=1.6)
    axis.plot([225, 225], [113, 399], color=MUTED, linewidth=1.6)
    for y in (113, 256, 399):
        add_arrow(axis, (225, y), (276, y))

    add_content_icon(axis, 325, 113)
    add_presentation_icon(axis, 325, 256)
    add_accuracy_icon(axis, 325, 399)

    add_judge_label(axis, 113, "CONTENT JUDGE × 6", ("one candidate fact per call",), CYAN)
    add_judge_label(axis, 256, "PRESENTATION JUDGE × 1", ("whole response + visible options",), PURPLE)
    add_judge_label(axis, 399, "ACCURACY JUDGE × 1", ("whole response + all six facts",), ORANGE)

    add_arrow(axis, (560, 113), (590, 113), CYAN)
    add_arrow(axis, (560, 256), (590, 256), PURPLE)
    add_arrow(axis, (560, 399), (590, 399), ORANGE)

    add_rounded_box(axis, 595, 67, 275, 92, WHITE, pale(CYAN, 0.3), 1.4, 10)
    add_rounded_box(axis, 595, 67, 8, 92, CYAN, CYAN, 0, 4)
    axis.text(625, 94, "CONTENT EXTRACTION", ha="left", va="center", color=TEXT, fontsize=13.5)
    axis.text(625, 125, "fact presence  ·  anchor presence", ha="left", va="center", color=MUTED, fontsize=11.5)
    axis.text(625, 147, "exact supporting excerpt", ha="left", va="center", color=MUTED, fontsize=11.5)

    add_arrow(axis, (870, 113), (944, 113), CYAN)
    add_rounded_box(axis, 950, 76, 220, 74, pale(CYAN), CYAN, 1.4, 10)
    axis.text(1060, 99, "CONTENT MEASURES", ha="center", va="center", color=TEXT, fontsize=12.5)
    axis.text(1060, 128, "D  ·  A  ·  T  ·  R", ha="center", va="center", color=NAVY, fontsize=17)

    add_rounded_box(axis, 707, 176, 285, 34, pale(PURPLE), PURPLE, 1.2, 17)
    axis.text(850, 193, "HIDDEN DIRECTION LABELS", ha="center", va="center", color=PURPLE, fontsize=11.5)
    axis.add_patch(
        FancyArrowPatch(
            (850, 176),
            (921, 116),
            arrowstyle="-|>",
            mutation_scale=11,
            linewidth=1.5,
            linestyle=(0, (5, 4)),
            color=PURPLE,
        )
    )

    add_output_card(
        axis,
        221,
        94,
        PURPLE,
        "PRESENTATION OUTCOMES",
        ("framing  ·  recommendation  ·  first option", "reassurance  ·  referral"),
    )
    add_output_card(
        axis,
        364,
        94,
        ORANGE,
        "ACCURACY OUTCOMES",
        ("unsupported or contradictory", "material claims"),
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(OUTPUT_PATH, facecolor=WHITE, bbox_inches=None, pad_inches=0)
    plt.close(figure)
    return OUTPUT_PATH


if __name__ == "__main__":
    print(generate_figure())
