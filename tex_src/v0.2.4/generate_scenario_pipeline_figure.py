"""Generate the scenario generation and curation pipeline figure."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Ellipse, FancyArrowPatch, FancyBboxPatch, Polygon

OUTPUT_PATH = Path(__file__).resolve().parent / "assets" / "scenario_generation_pipeline.pdf"

BLUE = "#2F8FFF"
ORANGE = "#FF7A2F"
GREEN = "#49C96B"
PINK = "#F05AA6"
TEXT = "#17212B"
MUTED = "#7A7F87"
BORDER = "#E1E3E6"
WHITE = "#FFFFFF"
PALE_GREY = "#F3F4F5"


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
    linewidth: float = 1.2,
    radius: float = 6,
) -> None:
    """Draw a rounded rectangle in the figure coordinate system."""
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


def add_flow_arrow(axis: Axes, start: float, end: float, label: str) -> None:
    """Connect adjacent stages with a labelled directional arrow."""
    axis.add_patch(
        FancyArrowPatch(
            (start, 156),
            (end, 156),
            arrowstyle="-|>",
            mutation_scale=13,
            linewidth=1.7,
            color=MUTED,
        )
    )
    axis.text((start + end) / 2, 137, label, ha="center", va="center", color=MUTED, fontsize=11)


def add_stage_text(axis: Axes, x: float, heading: str, detail: str) -> None:
    """Add one stage heading and its single concise explanatory line."""
    axis.text(x, 205, heading, ha="center", va="center", color=TEXT, fontsize=15, fontweight="normal")
    axis.text(x, 238, detail, ha="center", va="center", color=MUTED, fontsize=12, fontweight="normal")


def add_domain_seed_icon(axis: Axes, x: float) -> None:
    """Draw a scenario-brief document and seedling icon for the domain-seed stage."""
    axis.add_patch(Circle((x, 126), 54, facecolor=pale(BLUE), edgecolor=BLUE, linewidth=1.5))
    axis.plot(
        [x - 27, x + 10, x + 27, x + 27, x - 27, x - 27],
        [96, 96, 113, 158, 158, 96],
        color=BLUE,
        linewidth=2.5,
        solid_joinstyle="round",
    )
    axis.plot([x + 10, x + 10, x + 27], [96, 113, 113], color=BLUE, linewidth=2.5, solid_joinstyle="round")
    axis.plot([x, x], [143, 115], color=BLUE, linewidth=2.2, solid_capstyle="round")
    axis.add_patch(Ellipse((x - 9, 124), 20, 10, angle=35, facecolor="none", edgecolor=BLUE, linewidth=2.2))
    axis.add_patch(Ellipse((x + 10, 116), 20, 10, angle=-35, facecolor="none", edgecolor=BLUE, linewidth=2.2))


def add_robot_icon(axis: Axes, x: float) -> None:
    """Draw a robot icon for the model fact-generation stage."""
    axis.add_patch(Circle((x, 126), 54, facecolor=pale(ORANGE), edgecolor=ORANGE, linewidth=1.5))
    axis.plot([x, x], [91, 101], color=ORANGE, linewidth=2.5, solid_capstyle="round")
    axis.add_patch(Circle((x, 87), 4, facecolor=WHITE, edgecolor=ORANGE, linewidth=2))
    add_rounded_box(axis, x - 33, 102, 66, 49, "none", ORANGE, 2.5, 10)
    axis.add_patch(Circle((x - 14, 123), 4, facecolor=ORANGE, edgecolor="none"))
    axis.add_patch(Circle((x + 14, 123), 4, facecolor=ORANGE, edgecolor="none"))
    axis.plot([x - 15, x + 15], [139, 139], color=ORANGE, linewidth=2.5, solid_capstyle="round")
    axis.plot([x - 41, x - 33], [119, 119], color=ORANGE, linewidth=2.5, solid_capstyle="round")
    axis.plot([x + 33, x + 41], [119, 119], color=ORANGE, linewidth=2.5, solid_capstyle="round")


def add_review_icon(axis: Axes, x: float) -> None:
    """Draw a clipboard and pencil icon for researcher review."""
    axis.add_patch(Circle((x, 126), 54, facecolor=pale(GREEN), edgecolor=GREEN, linewidth=1.5))
    add_rounded_box(axis, x - 33, 96, 53, 62, "none", GREEN, 2.4, 5)
    add_rounded_box(axis, x - 18, 89, 23, 13, WHITE, GREEN, 2.2, 4)
    for top in (119, 141):
        axis.plot([x - 22, x - 16, x - 6], [top, top + 6, top - 6], color=GREEN, linewidth=2.4, solid_capstyle="round")
        axis.plot([x, x + 11], [top + 1, top + 1], color=GREEN, linewidth=2.2, solid_capstyle="round")
    axis.add_patch(
        Polygon(
            [(x + 16, 151), (x + 39, 128), (x + 47, 136), (x + 24, 159), (x + 13, 162)],
            closed=True,
            facecolor=WHITE,
            edgecolor=GREEN,
            linewidth=2.2,
        )
    )


def add_publish_icon(axis: Axes, x: float) -> None:
    """Draw an accepted-document icon for publication."""
    axis.add_patch(Circle((x, 126), 54, facecolor=pale(PINK), edgecolor=PINK, linewidth=1.5))
    axis.plot([x - 29, x + 12, x + 29, x + 29, x - 29, x - 29], [99, 99, 116, 156, 156, 99], color=PINK, linewidth=2.4)
    axis.plot([x + 12, x + 12, x + 29], [99, 116, 116], color=PINK, linewidth=2.4)
    axis.add_patch(Circle((x + 12, 143), 19, facecolor=pale(PINK), edgecolor=PINK, linewidth=2.2))
    axis.plot([x + 2, x + 10, x + 23], [143, 151, 136], color=PINK, linewidth=3, solid_capstyle="round")


def add_scenario_documents(axis: Axes, centres: Sequence[float], colour: str, checks: bool) -> None:
    """Draw five compact scenario-document markers."""
    for index, centre in enumerate(centres, start=1):
        add_rounded_box(axis, centre - 15, 262, 30, 40, WHITE, colour, 1.3, 3)
        if checks:
            axis.plot([centre - 7, centre - 2, centre + 7], [282, 287, 277], color=colour, linewidth=1.7, solid_capstyle="round")
        else:
            axis.text(centre, 283, f"S{index}", ha="center", va="center", color=TEXT, fontsize=10)


def add_generation_markers(axis: Axes, centres: Sequence[float]) -> None:
    """Draw five markers representing retained model generations."""
    for index, centre in enumerate(centres, start=1):
        axis.add_patch(Circle((centre, 282), 14, facecolor=pale(ORANGE), edgecolor=ORANGE, linewidth=1.2))
        axis.text(centre, 283, str(index), ha="center", va="center", color=TEXT, fontsize=10)


def add_review_markers(axis: Axes, centres: Sequence[float]) -> None:
    """Draw five check markers representing reviewed scenarios."""
    for centre in centres:
        axis.add_patch(Circle((centre, 282), 14, facecolor=pale(GREEN), edgecolor=GREEN, linewidth=1.2))
        axis.plot([centre - 7, centre - 2, centre + 7], [282, 287, 277], color=GREEN, linewidth=1.8, solid_capstyle="round")


def configure_canvas() -> tuple[Figure, Axes]:
    """Create a white vector canvas that matches the preview coordinate system."""
    figure, axis = plt.subplots(figsize=(1200 / 72, 385 / 72), facecolor=WHITE)
    axis.set_xlim(0, 1200)
    axis.set_ylim(385, 0)
    axis.axis("off")
    figure.subplots_adjust(left=0, right=1, top=1, bottom=0)
    return figure, axis


def generate_figure() -> Path:
    """Generate and save the scenario pipeline as a vector PDF."""
    figure, axis = configure_canvas()
    centres = (142.0, 430.0, 718.0, 1006.0)

    axis.text(600, 31, "REPEATED FOR EACH OF SIX FINANCIAL DOMAINS", ha="center", va="center", color=MUTED, fontsize=13)
    axis.plot([76, 1124], [48, 48], color=BORDER, linewidth=1)

    add_domain_seed_icon(axis, centres[0])
    add_stage_text(axis, centres[0], "1 · DOMAIN SEED", "five structured scenario briefs")
    add_scenario_documents(axis, (72, 107, 142, 177, 212), BLUE, checks=False)

    add_flow_arrow(axis, 252, 326, "each scenario")

    add_robot_icon(axis, centres[1])
    add_stage_text(axis, centres[1], "2 · FACT GENERATION", "GPT-5.4 · one retained run per scenario")
    add_generation_markers(axis, (360, 395, 430, 465, 500))

    add_flow_arrow(axis, 540, 614, "all outputs")

    add_review_icon(axis, centres[2])
    add_stage_text(axis, centres[2], "3 · RESEARCHER REVIEW", "review all five; correct where required")
    add_review_markers(axis, (648, 683, 718, 753, 788))

    add_flow_arrow(axis, 828, 902, "accepted only")

    add_publish_icon(axis, centres[3])
    add_stage_text(axis, centres[3], "4 · ACCEPT & PUBLISH", "five curated scenarios for evaluation")
    add_scenario_documents(axis, (936, 971, 1006, 1041, 1076), PINK, checks=True)

    axis.plot([244, 956], [345, 345], color=BORDER, linewidth=1)
    add_rounded_box(axis, 370, 324, 460, 42, PALE_GREY, BORDER, 1, 21)
    axis.text(
        600,
        346,
        "6 domains × 5 scenarios = 30 published scenario instances",
        ha="center",
        va="center",
        color=TEXT,
        fontsize=13,
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(OUTPUT_PATH, facecolor=WHITE, bbox_inches=None, pad_inches=0)
    plt.close(figure)
    return OUTPUT_PATH


if __name__ == "__main__":
    print(generate_figure())
