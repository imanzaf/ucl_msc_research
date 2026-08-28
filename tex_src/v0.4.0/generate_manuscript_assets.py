"""Generate the four dissertation figures derived from frozen results."""

from __future__ import annotations

import json
from collections import defaultdict
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Tuple, Union

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import TwoSlopeNorm
from matplotlib.lines import Line2D
from pydantic import BaseModel
from scipy.stats import pearsonr, spearmanr

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIRECTORY = Path(__file__).resolve().parent / "assets"
EXPERIMENT_ROOT = REPOSITORY_ROOT / "data" / "outputs" / "experiments"
SCENARIO_PATH = REPOSITORY_ROOT / "data" / "inputs" / "scenarios" / "v4.0.1" / "accepted_scenarios.jsonl"

COMMERCIAL_CONTRASTS_PATH = EXPERIMENT_ROOT / "commercial_interest_instruction_v1" / "scoring" / "paired_contrasts.json"
COMMERCIAL_SCORES_PATH = EXPERIMENT_ROOT / "commercial_interest_instruction_v1" / "scoring" / "response_scores.jsonl"
EXACT_BUDGET_SCORES_PATH = EXPERIMENT_ROOT / "information_budget_v1" / "scoring" / "response_scores.jsonl"
WORD_BUDGET_SCORES_PATH = EXPERIMENT_ROOT / "word_budget_external_validity_v1" / "scoring" / "response_scores.jsonl"
PRIMARY_RESULTS_PATH = EXPERIMENT_ROOT / "confirmatory_results.json"

SUMMARY_PATH = OUTPUT_DIRECTORY / "descriptive_analysis_summary.json"
BUDGET_MEANS_TABLE_PATH = OUTPUT_DIRECTORY / "budget_means_table.tex"
AGREEMENT_TABLE_PATH = OUTPUT_DIRECTORY / "selection_prose_agreement_table.tex"

MODEL_LABELS = {
    "anthropic/claude-sonnet-5": "Claude Sonnet 5",
    "deepseek/deepseek-v4-pro": "DeepSeek V4 Pro",
    "meta-llama/llama-3.3-70b-instruct": "Llama 3.3 70B Instruct",
    "meta-llama/llama-4-maverick": "Llama 4 Maverick",
    "openai/gpt-5.4": "GPT-5.4",
    "qwen/qwen-2.5-72b-instruct": "Qwen 2.5 72B Instruct",
    "qwen/qwen3.5-122b-a10b": "Qwen3.5 122B-A10B",
}
MODEL_ORDER = list(MODEL_LABELS)

TASK_COLUMNS: List[Tuple[str, int | None, str]] = [
    ("standard_comparison", None, "Standard"),
    ("single_most_important_fact", None, "Single fact"),
    ("exact_fact_budget", 2, "Exact $k=2$"),
    ("exact_fact_budget", 4, "Exact $k=4$"),
]

PRIMARY_TESTS: List[Tuple[str, str]] = [
    ("commercial_standard_D", "Commercial: standard"),
    ("commercial_single_fact_D", "Commercial: single priority"),
    ("commercial_exact_k4_D", "Commercial: exact $k=4$"),
    ("commercial_exact_k2_D", "Commercial: exact $k=2$"),
    ("commercial_ownership_flip_D", "Commercial: ownership flip"),
    ("anxious_vs_neutral_D", "Anxious minus neutral"),
    ("ordered_k6_k4_k2_selection_D", "Exact budget: $k=2$ minus $k=6$"),
]

EXPECTED_PRIMARY_VALUES = {
    "commercial_standard_D": (0.009, -0.001, 0.019),
    "commercial_single_fact_D": (0.044, 0.006, 0.085),
    "commercial_exact_k4_D": (0.034, 0.011, 0.058),
    "commercial_exact_k2_D": (0.105, 0.059, 0.153),
    "commercial_ownership_flip_D": (0.014, 0.008, 0.021),
    "anxious_vs_neutral_D": (-0.004, -0.013, 0.005),
    "ordered_k6_k4_k2_selection_D": (-0.029, -0.137, 0.079),
}

EXPECTED_FAMILY_SIZES = {
    "rq1_institutional_objective": 5,
    "rq2_customer_state": 1,
    "rq3_information_budget": 1,
}

EXPECTED_PRIMARY_P_VALUES = {
    "commercial_standard_D": (0.11985, 0.12418, "rq1_institutional_objective", 5),
    "commercial_single_fact_D": (0.06209, 0.12418, "rq1_institutional_objective", 5),
    "commercial_exact_k4_D": (0.02308, 0.06924, "rq1_institutional_objective", 5),
    "commercial_exact_k2_D": (0.00014, 0.00070, "rq1_institutional_objective", 5),
    "commercial_ownership_flip_D": (0.01624, 0.06496, "rq1_institutional_objective", 5),
    "anxious_vs_neutral_D": (0.53718, 0.53718, "rq2_customer_state", 1),
    "ordered_k6_k4_k2_selection_D": (0.70181, 0.70181, "rq3_information_budget", 1),
}

EXPECTED_HEATMAP = np.array(
    [
        [0.004, 0.044, 0.285, 0.185],
        [0.004, 0.037, 0.048, -0.022],
        [0.019, 0.059, 0.063, -0.041],
        [0.007, 0.044, 0.115, 0.037],
        [0.004, 0.056, 0.119, -0.019],
        [0.019, 0.070, 0.048, 0.033],
        [0.007, -0.004, 0.056, 0.067],
    ]
)

DOMAIN_COLOURS = {
    "Mortgage pricing, term and servicing choices": "#001A57",
    "Revolving credit, repayment and refinancing choices": "#00A6D6",
    "Savings rate, access and transfer choices": "#7B1FA2",
    "Investment-platform charges and service configurations": "#E85D75",
    "Insurance claim repair, replacement and cash-settlement choices": "#F6BE00",
    "International transfer pricing, speed and fee-allocation choices": "#2E7D32",
}
DOMAIN_LABELS = {
    "Mortgage pricing, term and servicing choices": "Mortgages",
    "Revolving credit, repayment and refinancing choices": "Credit and repayment",
    "Savings rate, access and transfer choices": "Savings",
    "Investment-platform charges and service configurations": "Investment platforms",
    "Insurance claim repair, replacement and cash-settlement choices": "Insurance settlements",
    "International transfer pricing, speed and fee-allocation choices": "International payments",
}

NAVY = "#001A57"
CYAN = "#00A6D6"
MID_GREY = "#5F6B7A"
LIGHT_GREY = "#D7DCE2"


class ManuscriptSummarySchemaVersion(str, Enum):
    """Identify the stable descriptive-analysis summary schema."""

    V1 = "1.0.0"


class DescriptiveAnalysisSummary(BaseModel):
    """Store the frozen descriptive results used by the v0.4.0 manuscript."""

    schema_version: ManuscriptSummarySchemaVersion = ManuscriptSummarySchemaVersion.V1
    budget_prevalence: Dict[str, Dict[str, Dict[str, Union[int, float]]]]
    commercial_k2_levels: Dict[str, Dict[str, Union[int, float]]]
    commercial_k2_transitions: Dict[str, Union[int, float]]
    selection_prose_agreement: Dict[str, Union[int, float]]
    scenario_domain_heterogeneity: Dict[str, object]


def read_jsonl(path: Path) -> Iterable[Dict[str, object]]:
    """Yield decoded objects from a JSON Lines artifact."""
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def configure_plot_style() -> None:
    """Apply a restrained and print-safe manuscript plotting style."""
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
            "font.size": 9,
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "axes.edgecolor": MID_GREY,
            "axes.linewidth": 0.8,
            "xtick.color": "#25313C",
            "ytick.color": "#25313C",
            "text.color": "#17212B",
            "pdf.fonttype": 42,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.08,
        }
    )


def load_commercial_contrasts() -> List[Dict[str, object]]:
    """Load the frozen response-paired commercial contrast records."""
    with COMMERCIAL_CONTRASTS_PATH.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    contrasts = payload["contrasts"]
    if not isinstance(contrasts, list):
        raise TypeError("commercial contrast artifact must contain a list of contrasts")
    return contrasts


def load_primary_results() -> List[Dict[str, object]]:
    """Load and validate seven primary results across the three research-question families."""
    with PRIMARY_RESULTS_PATH.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    tests = payload["tests"]
    if payload.get("holm_family_sizes") != EXPECTED_FAMILY_SIZES or not isinstance(tests, list) or len(tests) != 7:
        raise ValueError("primary result artifact must contain the five-test RQ1 family and singleton RQ2 and RQ3 families")
    tests_by_name = {str(row["test_name"]): row for row in tests}
    expected_names = [name for name, _ in PRIMARY_TESTS]
    if set(tests_by_name) != set(expected_names):
        raise ValueError("primary result artifact contains an unexpected test set")
    ordered = [tests_by_name[name] for name in expected_names]
    for row in ordered:
        interval = row["interval"]
        values = (
            round(float(row["estimate"]), 3),
            round(float(interval["lower"]), 3),
            round(float(interval["upper"]), 3),
        )
        if values != EXPECTED_PRIMARY_VALUES[str(row["test_name"])]:
            raise ValueError(f"primary result values changed for {row['test_name']}")
        p_values = (
            round(float(row["raw_p_value"]), 5),
            round(float(row["within_family_p_value"]), 5),
            str(row["multiplicity_family"]),
            int(row["multiplicity_family_size"]),
        )
        if p_values != EXPECTED_PRIMARY_P_VALUES[str(row["test_name"])]:
            raise ValueError(f"primary p-values or multiplicity family changed for {row['test_name']}")
    return ordered


def plot_primary_effects_forest(results: List[Dict[str, object]]) -> Path:
    """Plot point estimates and bootstrap intervals for the seven primary tests."""
    figure, axis = plt.subplots(figsize=(7.25, 4.55))
    positions = np.arange(len(results))[::-1]
    estimates = np.array([float(row["estimate"]) for row in results])
    lower = np.array([float(row["interval"]["lower"]) for row in results])
    upper = np.array([float(row["interval"]["upper"]) for row in results])
    labels = [label for _, label in PRIMARY_TESTS]

    axis.axvline(0, color="#25313C", linewidth=1.0)
    for position, row, estimate, low, high in zip(positions, results, estimates, lower, upper):
        adjusted_significant = float(row["within_family_p_value"]) < 0.05
        colour = "#C69200" if adjusted_significant else NAVY
        axis.hlines(position, low, high, color=colour, linewidth=2.2)
        axis.scatter(estimate, position, color=colour, s=52 if adjusted_significant else 38, zorder=3, edgecolor="white", linewidth=0.7)

    axis.set_yticks(positions, labels)
    axis.set_xlabel("Estimated directional change with pointwise 95% bootstrap interval")
    axis.set_xlim(-0.16, 0.18)
    axis.grid(axis="x", color=LIGHT_GREY, linewidth=0.7)
    axis.set_axisbelow(True)
    axis.spines[["top", "right", "left"]].set_visible(False)
    axis.tick_params(axis="y", length=0)
    axis.legend(
        handles=[Line2D([0], [0], marker="o", color="none", markerfacecolor="#C69200", markeredgecolor="none", label="RQ1 Holm-adjusted $p<0.05$")],
        loc="upper right",
        frameon=False,
        fontsize=8,
    )
    figure.tight_layout()

    output = OUTPUT_DIRECTORY / "primary_effects_forest.pdf"
    figure.savefig(output)
    plt.close(figure)
    return output


def select_directional_contrasts(contrasts: Iterable[Dict[str, object]], task: str, exact_budget: int | None) -> List[Dict[str, object]]:
    """Select one prose-direction commercial task from the contrast artifact."""
    return [
        row
        for row in contrasts
        if row["outcome_name"] == "prose_signed_directional_gap"
        and row["task"] == task
        and row["exact_fact_budget"] == exact_budget
        and row["ownership_role"] is None
    ]


def commercial_heatmap_values(contrasts: Iterable[Dict[str, object]]) -> np.ndarray:
    """Aggregate treatment-minus-control direction by model and task."""
    rows = list(contrasts)
    matrix = np.zeros((len(MODEL_ORDER), len(TASK_COLUMNS)))
    for column_index, (task, budget, _) in enumerate(TASK_COLUMNS):
        selected = select_directional_contrasts(rows, task, budget)
        for row_index, model_slug in enumerate(MODEL_ORDER):
            values = [float(row["treatment_minus_control"]) for row in selected if row["model_slug"] == model_slug]
            if len(values) != 90:
                raise ValueError(f"expected 90 commercial contrasts for {model_slug} and {task}, found {len(values)}")
            matrix[row_index, column_index] = float(np.mean(values))
    if not np.array_equal(np.round(matrix, 3), EXPECTED_HEATMAP):
        raise ValueError("model-by-task aggregates do not match the dissertation Results table")
    return matrix


def plot_commercial_heatmap(matrix: np.ndarray) -> Path:
    """Plot the seven-model by four-task commercial treatment heatmap."""
    figure, axis = plt.subplots(figsize=(7.25, 4.25))
    normalisation = TwoSlopeNorm(vmin=-0.20, vcenter=0.0, vmax=0.30)
    axis.pcolormesh(
        np.arange(matrix.shape[1] + 1),
        np.arange(matrix.shape[0] + 1),
        matrix,
        cmap="PuOr_r",
        norm=normalisation,
        edgecolors="white",
        linewidth=1.5,
        shading="flat",
        rasterized=False,
    )

    axis.set_xticks(np.arange(len(TASK_COLUMNS)) + 0.5, [column[2] for column in TASK_COLUMNS])
    axis.set_yticks(np.arange(len(MODEL_ORDER)) + 0.5, [MODEL_LABELS[slug] for slug in MODEL_ORDER])
    axis.invert_yaxis()
    axis.tick_params(axis="x", pad=7)
    axis.tick_params(axis="y", pad=5)
    axis.set_title("Commercial-interest effects are largest under the tightest exact budget", loc="left", weight="bold")

    for row_index in range(matrix.shape[0]):
        for column_index in range(matrix.shape[1]):
            value = matrix[row_index, column_index]
            text_colour = "white" if abs(value) >= 0.13 else "#17212B"
            axis.text(
                column_index + 0.5,
                row_index + 0.5,
                f"{value:.3f}",
                ha="center",
                va="center",
                color=text_colour,
                weight="bold",
            )

    colour_axis = axis.inset_axes([1.035, 0.0, 0.035, 1.0])
    colour_edges = np.linspace(-0.20, 0.30, 129)
    colour_values = ((colour_edges[:-1] + colour_edges[1:]) / 2).reshape(-1, 1)
    colour_axis.pcolormesh(
        [0, 1],
        colour_edges,
        colour_values,
        cmap="PuOr_r",
        norm=normalisation,
        shading="flat",
        rasterized=False,
    )
    colour_axis.set_xticks([])
    colour_axis.set_yticks(np.arange(-0.2, 0.31, 0.1))
    colour_axis.yaxis.tick_right()
    colour_axis.yaxis.set_label_position("right")
    colour_axis.set_ylabel("Treatment minus control $\\Delta D$", labelpad=8)
    colour_axis.tick_params(axis="y", length=2.5, labelsize=8)

    output = OUTPUT_DIRECTORY / "commercial_model_task_heatmap.pdf"
    figure.savefig(output)
    plt.close(figure)
    return output


def load_scenario_domains() -> Dict[str, str]:
    """Map every accepted scenario identifier to its financial domain."""
    domains = {str(row["scenario_id"]): str(row["domain"]) for row in read_jsonl(SCENARIO_PATH)}
    if len(domains) != 30:
        raise ValueError(f"expected 30 accepted scenarios, found {len(domains)}")
    missing_colours = set(domains.values()) - set(DOMAIN_COLOURS)
    if missing_colours:
        raise ValueError(f"missing plot colours for domains: {sorted(missing_colours)}")
    return domains


def scenario_k2_effects(contrasts: Iterable[Dict[str, object]]) -> List[Tuple[str, float]]:
    """Average the commercial exact-k=2 direction contrast within scenario."""
    selected = select_directional_contrasts(contrasts, "exact_fact_budget", 2)
    by_scenario: Dict[str, List[float]] = defaultdict(list)
    models_by_scenario: Dict[str, set[str]] = defaultdict(set)
    for row in selected:
        scenario_id = str(row["scenario_id"])
        by_scenario[scenario_id].append(float(row["treatment_minus_control"]))
        models_by_scenario[scenario_id].add(str(row["model_slug"]))
    if len(by_scenario) != 30:
        raise ValueError(f"expected 30 scenario-level k=2 effects, found {len(by_scenario)}")
    for scenario_id, values in by_scenario.items():
        if len(values) != 21 or len(models_by_scenario[scenario_id]) != 7:
            raise ValueError(f"scenario {scenario_id} does not contain 3 affects by 7 models")
    effects = sorted(((scenario_id, float(np.mean(values))) for scenario_id, values in by_scenario.items()), key=lambda item: item[1])
    aggregate = float(np.mean([value for _, value in effects]))
    if round(aggregate, 3) != 0.105:
        raise ValueError("scenario-level k=2 effects do not reproduce the reported aggregate treatment effect")
    return effects


def plot_scenario_k2_effects(effects: List[Tuple[str, float]], domains: Dict[str, str]) -> Path:
    """Plot ordered scenario-level commercial exact-k=2 treatment effects."""
    figure, axis = plt.subplots(figsize=(7.25, 8.5))
    positions = np.arange(len(effects))
    values = np.array([effect for _, effect in effects])
    colours = [DOMAIN_COLOURS[domains[scenario_id]] for scenario_id, _ in effects]

    axis.axvline(0, color="#25313C", linewidth=1.0)
    axis.hlines(positions, 0, values, color=colours, linewidth=1.6, alpha=0.78)
    axis.scatter(values, positions, c=colours, s=32, edgecolor="white", linewidth=0.6, zorder=3)
    axis.set_yticks(positions, [scenario_id for scenario_id, _ in effects])
    axis.set_xlabel("Commercial instruction minus control $\\Delta D$ at exact $k=2$")
    axis.set_title("The aggregate exact-$k=2$ effect varies across the 30 scenario instances", loc="left", weight="bold")
    axis.grid(axis="x", color=LIGHT_GREY, linewidth=0.7)
    axis.set_axisbelow(True)
    axis.spines[["top", "right", "left"]].set_visible(False)
    axis.tick_params(axis="y", length=0)

    handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            color="none",
            markerfacecolor=colour,
            markeredgecolor="none",
            label=DOMAIN_LABELS[domain],
        )
        for domain, colour in DOMAIN_COLOURS.items()
    ]
    axis.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.09), ncol=2, frameon=False, fontsize=7.5)

    output = OUTPUT_DIRECTORY / "commercial_k2_scenario_effects.pdf"
    figure.savefig(output)
    plt.close(figure)
    return output


def _percentage(count: int, total: int) -> float:
    """Convert one count to a percentage."""
    if total <= 0:
        raise ValueError("percentage denominator must be positive")
    return 100.0 * count / total


def _summarise_prevalence(rows: List[Dict[str, object]], metric_name: str) -> Dict[str, Union[int, float]]:
    """Summarise response-level coverage, imbalance and direction prevalence."""
    values: List[Tuple[float, float, float]] = []
    for row in rows:
        metrics = row[metric_name]
        if not isinstance(metrics, dict):
            raise ValueError(f"{metric_name} must be present for every selected row")
        if metric_name == "exact_selection":
            cell = row["cell"]
            if not isinstance(cell, dict) or cell.get("exact_fact_budget") is None:
                raise ValueError("exact-selection prevalence requires an exact fact budget")
            coverage = float(cell["exact_fact_budget"]) / 6.0
        else:
            coverage = float(metrics["total_material_coverage"])
        values.append(
            (
                coverage,
                float(metrics["pairwise_absolute_imbalance"]),
                float(metrics["signed_directional_gap"]),
            )
        )
    total = len(values)
    if total != 210:
        raise ValueError(f"expected 210 responses for one budget coordinate, found {total}")
    complete = sum(abs(coverage - 1.0) <= 1e-12 for coverage, _, _ in values)
    pairwise_balanced = sum(abs(imbalance) <= 1e-12 for _, imbalance, _ in values)
    net_neutral = sum(abs(direction) <= 1e-12 for _, _, direction in values)
    neutral_with_broken_pair = sum(abs(direction) <= 1e-12 and imbalance > 1e-12 for _, imbalance, direction in values)
    return {
        "n": total,
        "complete_percent": _percentage(complete, total),
        "pairwise_balanced_percent": _percentage(pairwise_balanced, total),
        "net_neutral_percent": _percentage(net_neutral, total),
        "incomplete_percent": _percentage(total - complete, total),
        "broken_pair_percent": _percentage(total - pairwise_balanced, total),
        "nonzero_direction_percent": _percentage(total - net_neutral, total),
        "neutral_with_broken_pair_percent": _percentage(neutral_with_broken_pair, total),
        "mean_coverage": float(np.mean([coverage for coverage, _, _ in values])),
        "mean_imbalance": float(np.mean([imbalance for _, imbalance, _ in values])),
        "mean_direction": float(np.mean([direction for _, _, direction in values])),
    }


def load_budget_prevalence() -> Dict[str, Dict[str, Dict[str, Union[int, float]]]]:
    """Load and validate response-level prevalence across exact and natural budgets."""
    exact_rows = list(read_jsonl(EXACT_BUDGET_SCORES_PATH))
    natural_rows = list(read_jsonl(WORD_BUDGET_SCORES_PATH))
    exact = {
        str(budget): _summarise_prevalence(
            [
                row
                for row in exact_rows
                if row["cell"].get("affect") == "neutral" and row["cell"].get("exact_fact_budget") == budget
            ],
            "exact_selection",
        )
        for budget in [2, 4, 6]
    }
    natural = {
        str(budget): _summarise_prevalence(
            [row for row in natural_rows if row["cell"].get("word_budget") == budget],
            "prose_selection",
        )
        for budget in [40, 80, 160]
    }
    if [round(natural[str(budget)]["complete_percent"], 1) for budget in [40, 80, 160]] != [27.6, 63.3, 90.5]:
        raise ValueError("natural-budget completeness prevalence changed from the frozen analysis")
    if [round(natural[str(budget)]["pairwise_balanced_percent"], 1) for budget in [40, 80, 160]] != [37.6, 67.1, 90.5]:
        raise ValueError("natural-budget pairwise-balance prevalence changed from the frozen analysis")
    if [round(natural[str(budget)]["net_neutral_percent"], 1) for budget in [40, 80, 160]] != [46.2, 71.0, 90.5]:
        raise ValueError("natural-budget net-neutral prevalence changed from the frozen analysis")
    if [round(exact[str(budget)]["broken_pair_percent"], 1) for budget in [2, 4, 6]] != [77.1, 69.5, 0.0]:
        raise ValueError("exact-budget broken-pair prevalence changed from the frozen analysis")
    return {"exact_selection_neutral": exact, "natural_prose": natural}


def load_commercial_k2_levels() -> Dict[str, Dict[str, Union[int, float]]]:
    """Summarise control and treatment levels for the commercial exact-k=2 task."""
    all_rows = list(read_jsonl(COMMERCIAL_SCORES_PATH))
    summaries: Dict[str, Dict[str, Union[int, float]]] = {}
    for manuscript_label, instruction in [("control", "control"), ("commercial_objective", "protect_commercial_interests")]:
        rows = [
            row
            for row in all_rows
            if row["cell"].get("task") == "exact_fact_budget"
            and row["cell"].get("exact_fact_budget") == 2
            and row["cell"].get("instruction") == instruction
        ]
        if len(rows) != 630:
            raise ValueError(f"expected 630 commercial k=2 responses for {instruction}, found {len(rows)}")
        directions = [float(row["prose_selection"]["signed_directional_gap"]) for row in rows]
        summaries[manuscript_label] = {
            "n": len(rows),
            "mean_coverage": float(np.mean([float(row["prose_selection"]["total_material_coverage"]) for row in rows])),
            "mean_imbalance": float(np.mean([float(row["prose_selection"]["pairwise_absolute_imbalance"]) for row in rows])),
            "mean_direction": float(np.mean(directions)),
            "institution_supporting_first_fact_percent": _percentage(
                sum(row["presentation"]["first_material_fact"] == "owner_supporting" for row in rows),
                len(rows),
            ),
            "institution_supporting_framing_percent": _percentage(
                sum(row["presentation"]["framing_direction"] == "owner_favouring" for row in rows),
                len(rows),
            ),
            "mean_words": float(np.mean([float(row["secondary"]["response_word_count"]) for row in rows])),
            "positive_direction_percent": _percentage(sum(direction > 1e-12 for direction in directions), len(rows)),
            "negative_direction_percent": _percentage(sum(direction < -1e-12 for direction in directions), len(rows)),
            "neutral_direction_percent": _percentage(sum(abs(direction) <= 1e-12 for direction in directions), len(rows)),
        }
    expected = {
        "control": (0.471, 0.595, -0.003),
        "commercial_objective": (0.463, 0.605, 0.102),
    }
    for label, values in summaries.items():
        observed = (round(float(values["mean_coverage"]), 3), round(float(values["mean_imbalance"]), 3), round(float(values["mean_direction"]), 3))
        if observed != expected[label]:
            raise ValueError(f"commercial k=2 levels changed for {label}")
    return summaries


def _commercial_k2_contrasts(contrasts: Iterable[Dict[str, object]], outcome_name: str) -> List[Dict[str, object]]:
    """Select one exact-k=2 commercial contrast outcome."""
    return [
        row
        for row in contrasts
        if row["task"] == "exact_fact_budget"
        and row["exact_fact_budget"] == 2
        and row["ownership_role"] is None
        and row["outcome_name"] == outcome_name
    ]


def load_commercial_k2_transitions(contrasts: Iterable[Dict[str, object]]) -> Dict[str, Union[int, float]]:
    """Summarise customer-visible direction movement under the commercial objective."""
    rows = _commercial_k2_contrasts(contrasts, "prose_signed_directional_gap")
    changes = [float(row["treatment_minus_control"]) for row in rows]
    if len(changes) != 630:
        raise ValueError(f"expected 630 prose direction contrasts at commercial k=2, found {len(changes)}")
    toward = sum(change > 1e-12 for change in changes)
    unchanged = sum(abs(change) <= 1e-12 for change in changes)
    away = sum(change < -1e-12 for change in changes)
    if (toward, unchanged, away) != (197, 330, 103):
        raise ValueError("commercial k=2 prose transition counts changed from the frozen analysis")
    return {
        "n": len(changes),
        "toward_institution_count": toward,
        "unchanged_count": unchanged,
        "away_from_institution_count": away,
        "toward_institution_percent": _percentage(toward, len(changes)),
        "unchanged_percent": _percentage(unchanged, len(changes)),
        "away_from_institution_percent": _percentage(away, len(changes)),
    }


def load_selection_prose_agreement(contrasts: Iterable[Dict[str, object]]) -> Dict[str, Union[int, float]]:
    """Measure exploratory agreement between declared-selection and prose direction changes."""
    rows = list(contrasts)
    coordinate_fields = ("scenario_id", "model_slug", "affect", "task", "exact_fact_budget", "ownership_role", "rendering")

    def coordinate(row: Dict[str, object]) -> Tuple[object, ...]:
        """Build the matched response coordinate shared by two outcomes."""
        return tuple(row[field] for field in coordinate_fields)

    prose = {
        coordinate(row): float(row["treatment_minus_control"])
        for row in _commercial_k2_contrasts(rows, "prose_signed_directional_gap")
    }
    selected = {
        coordinate(row): float(row["treatment_minus_control"])
        for row in _commercial_k2_contrasts(rows, "selected_id_signed_directional_gap")
    }
    shared = sorted(set(prose) & set(selected))
    if len(shared) != 629:
        raise ValueError(f"expected 629 usable selection-prose contrast pairs, found {len(shared)}")
    selected_changes = [selected[key] for key in shared]
    prose_changes = [prose[key] for key in shared]
    pearson = float(pearsonr(selected_changes, prose_changes).statistic)
    spearman = float(spearmanr(selected_changes, prose_changes).statistic)
    toward = sum(change > 1e-12 for change in selected_changes)
    unchanged = sum(abs(change) <= 1e-12 for change in selected_changes)
    away = sum(change < -1e-12 for change in selected_changes)
    if (toward, unchanged, away) != (118, 471, 40) or (round(pearson, 3), round(spearman, 3)) != (0.822, 0.723):
        raise ValueError("selection-prose agreement changed from the frozen analysis")
    return {
        "n": len(shared),
        "selection_toward_institution_percent": _percentage(toward, len(shared)),
        "selection_unchanged_percent": _percentage(unchanged, len(shared)),
        "selection_away_from_institution_percent": _percentage(away, len(shared)),
        "pearson_r": pearson,
        "spearman_rho": spearman,
    }


def load_scenario_domain_heterogeneity(contrasts: Iterable[Dict[str, object]]) -> Dict[str, object]:
    """Summarise descriptive scenario and domain heterogeneity at commercial exact-k=2."""
    effects = scenario_k2_effects(contrasts)
    domains = load_scenario_domains()
    domain_values: Dict[str, List[float]] = defaultdict(list)
    for scenario_id, effect in effects:
        domain_values[domains[scenario_id]].append(effect)
    domain_means = {DOMAIN_LABELS[domain]: float(np.mean(values)) for domain, values in domain_values.items()}
    values = [effect for _, effect in effects]
    positive = sum(effect > 1e-12 for effect in values)
    zero = sum(abs(effect) <= 1e-12 for effect in values)
    negative = sum(effect < -1e-12 for effect in values)
    if (positive, zero, negative) != (22, 1, 7) or len(domain_means) != 6 or not all(value > 0 for value in domain_means.values()):
        raise ValueError("scenario or domain heterogeneity changed from the frozen analysis")
    return {
        "scenario_count": len(values),
        "positive_scenario_count": positive,
        "zero_scenario_count": zero,
        "negative_scenario_count": negative,
        "positive_domain_count": sum(value > 0 for value in domain_means.values()),
        "domain_count": len(domain_means),
        "domain_mean_direction_changes": dict(sorted(domain_means.items())),
    }


def build_descriptive_analysis_summary(contrasts: Iterable[Dict[str, object]]) -> DescriptiveAnalysisSummary:
    """Build the schema-versioned descriptive summary from frozen artifacts."""
    rows = list(contrasts)
    return DescriptiveAnalysisSummary(
        budget_prevalence=load_budget_prevalence(),
        commercial_k2_levels=load_commercial_k2_levels(),
        commercial_k2_transitions=load_commercial_k2_transitions(rows),
        selection_prose_agreement=load_selection_prose_agreement(rows),
        scenario_domain_heterogeneity=load_scenario_domain_heterogeneity(rows),
    )


def write_descriptive_analysis_summary(summary: DescriptiveAnalysisSummary) -> Path:
    """Write the stable descriptive-analysis JSON artifact."""
    SUMMARY_PATH.write_text(summary.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return SUMMARY_PATH


def write_budget_means_table(summary: DescriptiveAnalysisSummary) -> Path:
    """Write the compact mean-score table for exact and natural budgets."""
    rows: List[str] = []
    for contract, key, budgets, label in [
        ("Declared exact selection", "exact_selection_neutral", [2, 4, 6], r"$k={}$"),
        ("Realised prose", "natural_prose", [40, 80, 160], r"{} words"),
    ]:
        for budget in budgets:
            values = summary.budget_prevalence[key][str(budget)]
            rows.append(
                f"{contract} & {label.format(budget)} & {float(values['mean_coverage']):.3f} & "
                f"{float(values['mean_imbalance']):.3f} & {float(values['mean_direction']):.3f} \\\\"
            )
    BUDGET_MEANS_TABLE_PATH.write_text(
        "\n".join(
            [
                "% Generated from frozen response scores; do not edit manually.",
                r"\begin{tabularx}{\textwidth}{@{}YYrrr@{}}",
                r"\toprule",
                r"\textbf{Response contract} & \textbf{Budget} & $\boldsymbol{T}$ & $\boldsymbol{A}$ & $\boldsymbol{D}$ \\",
                r"\midrule",
                *rows,
                r"\bottomrule",
                r"\end{tabularx}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return BUDGET_MEANS_TABLE_PATH


def write_selection_prose_agreement_table(summary: DescriptiveAnalysisSummary) -> Path:
    """Write the exploratory selection-prose agreement appendix table."""
    values = summary.selection_prose_agreement
    AGREEMENT_TABLE_PATH.write_text(
        "\n".join(
            [
                "% Generated from frozen commercial contrasts; do not edit manually.",
                r"\begin{tabularx}{0.94\textwidth}{@{}Yrrrrrr@{}}",
                r"\toprule",
                r"\textbf{Comparison} & \textbf{$n$} & \textbf{Towards} & \textbf{Unchanged} & \textbf{Away} & $\boldsymbol{r}$ & $\boldsymbol{\rho}$ \\",
                r"\midrule",
                (
                    f"Declared-selection versus prose change & {int(values['n'])} & "
                    f"{float(values['selection_toward_institution_percent']):.1f}\\% & "
                    f"{float(values['selection_unchanged_percent']):.1f}\\% & "
                    f"{float(values['selection_away_from_institution_percent']):.1f}\\% & "
                    f"{float(values['pearson_r']):.3f} & {float(values['spearman_rho']):.3f} \\\\"
                ),
                r"\bottomrule",
                r"\end{tabularx}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return AGREEMENT_TABLE_PATH


def plot_budget_prevalence(summary: DescriptiveAnalysisSummary) -> Path:
    """Plot response-level completeness, pairwise balance and net neutrality by budget."""
    figure, axes = plt.subplots(1, 2, figsize=(7.25, 3.85), sharey=True)
    panels = [
        (axes[0], "exact_selection_neutral", [2, 4, 6], "Declared exact selection", "Selected facts permitted"),
        (axes[1], "natural_prose", [40, 80, 160], "Realised prose under word limits", "Maximum words requested"),
    ]
    series = [
        ("complete_percent", "Complete $T=1$", NAVY, "o"),
        ("pairwise_balanced_percent", "Pairwise balanced $A=0$", CYAN, "s"),
        ("net_neutral_percent", "Net-neutral $D=0$", "#7B1FA2", "^"),
    ]
    for axis, key, budgets, title, xlabel in panels:
        values = summary.budget_prevalence[key]
        for metric, label, colour, marker in series:
            axis.plot(
                budgets,
                [float(values[str(budget)][metric]) for budget in budgets],
                color=colour,
                marker=marker,
                linewidth=2.1,
                label=label,
            )
        axis.set_title(title, weight="bold")
        axis.set_xlabel(xlabel)
        axis.set_xticks(budgets)
        axis.set_ylim(0, 103)
        axis.grid(axis="y", color=LIGHT_GREY, linewidth=0.7)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Responses (%)")
    axes[1].legend(loc="lower right", frameon=False, fontsize=8)
    figure.suptitle("More response space increases completeness and matched-pair integrity", x=0.04, ha="left", weight="bold")
    figure.tight_layout(rect=(0, 0, 1, 0.91), w_pad=2.4)
    output = OUTPUT_DIRECTORY / "budget_prevalence.pdf"
    figure.savefig(output)
    plt.close(figure)
    return output


def plot_commercial_k2_composition(summary: DescriptiveAnalysisSummary) -> Path:
    """Plot commercial exact-k=2 composition levels and response-paired direction movement."""
    figure, axes = plt.subplots(1, 2, figsize=(7.25, 3.95))
    control = summary.commercial_k2_levels["control"]
    treatment = summary.commercial_k2_levels["commercial_objective"]
    metrics = ["mean_coverage", "mean_imbalance", "mean_direction"]
    metric_labels = ["Coverage $T$", "Imbalance $A$", "Direction $D$"]
    positions = np.arange(len(metrics))
    width = 0.34
    control_values = [float(control[metric]) for metric in metrics]
    treatment_values = [float(treatment[metric]) for metric in metrics]
    axes[0].bar(positions - width / 2, control_values, width, color=MID_GREY, label="Control")
    axes[0].bar(positions + width / 2, treatment_values, width, color=NAVY, label="Commercial objective")
    axes[0].axhline(0, color="#25313C", linewidth=0.8)
    axes[0].set_xticks(positions, metric_labels)
    axes[0].set_ylim(-0.08, 0.68)
    axes[0].set_ylabel("Mean response-level score")
    axes[0].set_title("Similar disclosure, different direction", weight="bold")
    axes[0].legend(frameon=False, fontsize=8)
    axes[0].grid(axis="y", color=LIGHT_GREY, linewidth=0.7)
    axes[0].set_axisbelow(True)
    for position, values in enumerate(zip(control_values, treatment_values)):
        for offset, value in zip([-width / 2, width / 2], values):
            vertical_alignment = "top" if value < 0 else "bottom"
            axes[0].text(position + offset, value + (-0.012 if value < 0 else 0.012), f"{value:.3f}", ha="center", va=vertical_alignment, fontsize=7.5)

    transitions = summary.commercial_k2_transitions
    labels = ["Towards\ninstitution", "Unchanged", "Away from\ninstitution"]
    transition_values = [
        float(transitions["toward_institution_percent"]),
        float(transitions["unchanged_percent"]),
        float(transitions["away_from_institution_percent"]),
    ]
    bars = axes[1].bar(labels, transition_values, color=[NAVY, MID_GREY, CYAN], width=0.62)
    axes[1].set_ylim(0, 60)
    axes[1].set_ylabel("Matched response pairs (%)")
    axes[1].set_title("Direction of treatment-associated movement", weight="bold")
    axes[1].grid(axis="y", color=LIGHT_GREY, linewidth=0.7)
    axes[1].set_axisbelow(True)
    axes[1].bar_label(bars, labels=[f"{value:.1f}%" for value in transition_values], padding=3, fontsize=8)
    for axis in axes:
        axis.spines[["top", "right"]].set_visible(False)
    figure.suptitle("Same amount of information, different composition", x=0.04, ha="left", weight="bold")
    figure.tight_layout(rect=(0, 0, 1, 0.91), w_pad=2.2)
    output = OUTPUT_DIRECTORY / "commercial_k2_composition.pdf"
    figure.savefig(output)
    plt.close(figure)
    return output


def main() -> None:
    """Generate and validate every result-derived dissertation asset."""
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    configure_plot_style()
    contrasts = load_commercial_contrasts()
    heatmap = commercial_heatmap_values(contrasts)
    effects = scenario_k2_effects(contrasts)
    domains = load_scenario_domains()
    summary = build_descriptive_analysis_summary(contrasts)
    outputs = [
        write_descriptive_analysis_summary(summary),
        write_budget_means_table(summary),
        write_selection_prose_agreement_table(summary),
        plot_primary_effects_forest(load_primary_results()),
        plot_commercial_heatmap(heatmap),
        plot_scenario_k2_effects(effects, domains),
        plot_budget_prevalence(summary),
        plot_commercial_k2_composition(summary),
    ]
    for output in outputs:
        print(output.relative_to(REPOSITORY_ROOT))


if __name__ == "__main__":
    main()
