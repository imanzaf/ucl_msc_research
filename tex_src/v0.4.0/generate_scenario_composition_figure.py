"""Generate the conceptual scenario-composition figure for the dissertation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch

OUTPUT_PATH = Path(__file__).resolve().parent / "assets" / "scenario_composition_diagram.pdf"

NAVY = "#001A57"
CYAN = "#00A6D6"
PURPLE = "#7B1FA2"
GOLD_PALE = "#FFF4C2"
GOLD_TEXT = "#5D4800"
GREY_PALE = "#EDF0F3"
GREY_TEXT = "#3F4955"
MID_GREY = "#5F6B7A"
LIGHT_GREY = "#D7DCE2"
TEXT = "#17212B"
WHITE = "#FFFFFF"
CYAN_PALE = "#E8F7FB"


@dataclass(frozen=True)
class PairRow:
    """Describe the two fact directions and shared valence in one matched pair."""

    number: int
    top: float
    valence: Literal["FAVOURABLE", "ADVERSE"]
    option_a_direction: Literal["Institution-supporting", "Countervailing"]
    option_b_direction: Literal["Institution-supporting", "Countervailing"]


PAIR_ROWS: Sequence[PairRow] = (
    PairRow(1, 165, "FAVOURABLE", "Institution-supporting", "Countervailing"),
    PairRow(2, 305, "ADVERSE", "Countervailing", "Institution-supporting"),
    PairRow(3, 445, "FAVOURABLE", "Institution-supporting", "Countervailing"),
)


def add_rounded_box(
    axis: Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    facecolour: str,
    edgecolour: str = "none",
    linewidth: float = 0,
    radius: float = 8,
) -> None:
    """Add a rounded rectangle using the figure's coordinate system."""
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


def add_option_header(axis: Axes, x: float, title: str) -> None:
    """Draw an option header and its three-fact annotation."""
    add_rounded_box(axis, x, 76, 390, 64, NAVY)
    axis.text(x + 195, 105, title, ha="center", va="center", color=WHITE, fontsize=23, fontweight="normal")
    axis.text(x + 195, 127, "three material facts", ha="center", va="center", color="#DCE9FF", fontsize=15)


def direction_colour(direction: str) -> str:
    """Return the palette colour used for an institutional-direction label."""
    return CYAN if direction == "Institution-supporting" else PURPLE


def add_fact_card(
    axis: Axes,
    x: float,
    y: float,
    title: str,
    direction: str,
    strip_side: Literal["left", "right"],
) -> None:
    """Draw one fact card with a text label and direction stripe."""
    add_rounded_box(axis, x, y, 390, 90, WHITE, LIGHT_GREY, 1.5)
    strip_x = x if strip_side == "left" else x + 381
    add_rounded_box(axis, strip_x, y, 9, 90, direction_colour(direction), radius=4)
    axis.text(x + 30, y + 37, title, ha="left", va="center", color=TEXT, fontsize=21, fontweight="normal")
    axis.text(
        x + 30,
        y + 66,
        direction,
        ha="left",
        va="center",
        color=NAVY if direction == "Institution-supporting" else PURPLE,
        fontsize=15,
        fontweight="normal",
    )


def add_pair_annotation(axis: Axes, row: PairRow) -> None:
    """Connect two fact cards and label their shared pair and customer valence."""
    centre_y = row.top + 45
    axis.plot([510, 690], [centre_y, centre_y], color=CYAN, linewidth=2, zorder=0)
    axis.add_patch(Circle((510, centre_y), radius=4, facecolor=CYAN, edgecolor="none"))
    axis.add_patch(Circle((690, centre_y), radius=4, facecolor=CYAN, edgecolor="none"))

    add_rounded_box(axis, 544, row.top + 4, 112, 29, CYAN_PALE, CYAN, 1.2, 14)
    axis.text(600, row.top + 20, f"PAIR {row.number}", ha="center", va="center", color=NAVY, fontsize=14, fontweight="normal")

    if row.valence == "FAVOURABLE":
        add_rounded_box(axis, 536, row.top + 54, 128, 27, GOLD_PALE, radius=13)
        label = "+ FAVOURABLE"
        label_colour = GOLD_TEXT
    else:
        add_rounded_box(axis, 542, row.top + 54, 116, 27, GREY_PALE, radius=13)
        label = "- ADVERSE"
        label_colour = GREY_TEXT
    axis.text(600, row.top + 68, label, ha="center", va="center", color=label_colour, fontsize=13, fontweight="normal")


def add_pair_row(axis: Axes, row: PairRow) -> None:
    """Draw both facts and annotations for one matched pair."""
    add_pair_annotation(axis, row)
    add_fact_card(axis, 120, row.top, f"Fact A{row.number}", row.option_a_direction, "left")
    add_fact_card(axis, 690, row.top, f"Fact B{row.number}", row.option_b_direction, "right")


def configure_canvas() -> tuple[Figure, Axes]:
    """Create a white, borderless vector canvas in manuscript proportions."""
    # Match the 1200-by-560 SVG coordinate system one-for-one in PDF points so
    # text, strokes and spacing scale together when LaTeX fits the figure.
    figure, axis = plt.subplots(figsize=(1200 / 72, 560 / 72), facecolor=WHITE)
    axis.set_xlim(0, 1200)
    axis.set_ylim(560, 0)
    axis.axis("off")
    figure.subplots_adjust(left=0, right=1, top=1, bottom=0)
    return figure, axis


def generate_figure() -> Path:
    """Generate and save the scenario-composition diagram as a vector PDF."""
    figure, axis = configure_canvas()

    axis.add_patch(FancyArrowPatch((360, 42), (150, 42), arrowstyle="-|>", mutation_scale=11, linewidth=1.5, color=MID_GREY))
    axis.add_patch(FancyArrowPatch((840, 42), (1050, 42), arrowstyle="-|>", mutation_scale=11, linewidth=1.5, color=MID_GREY))
    axis.text(
        600,
        42,
        "TWO MUTUALLY EXCLUSIVE OPTIONS",
        ha="center",
        va="center",
        color=TEXT,
        fontsize=16,
        fontweight="normal",
    )

    add_option_header(axis, 120, "Option A")
    add_option_header(axis, 690, "Option B")

    axis.plot([82, 65, 65, 82], [165, 165, 535, 535], color=MID_GREY, linewidth=1.6)
    axis.text(38, 350, "SIX MATERIAL FACTS", ha="center", va="center", rotation=90, color=TEXT, fontsize=15, fontweight="normal")

    for row in PAIR_ROWS:
        add_pair_row(axis, row)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(OUTPUT_PATH, facecolor=WHITE, bbox_inches=None, pad_inches=0)
    plt.close(figure)
    return OUTPUT_PATH


if __name__ == "__main__":
    print(generate_figure())
