"""Generate the four dissertation figures derived from frozen results."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import TwoSlopeNorm
from matplotlib.lines import Line2D

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIRECTORY = Path(__file__).resolve().parent / "assets"
EXPERIMENT_ROOT = REPOSITORY_ROOT / "data" / "outputs" / "experiments"
SCENARIO_PATH = REPOSITORY_ROOT / "data" / "inputs" / "scenarios" / "v4.0.1" / "accepted_scenarios.jsonl"

COMMERCIAL_CONTRASTS_PATH = EXPERIMENT_ROOT / "commercial_interest_instruction_v1" / "scoring" / "paired_contrasts.json"
EXACT_BUDGET_SCORES_PATH = EXPERIMENT_ROOT / "information_budget_v1" / "scoring" / "response_scores.jsonl"
WORD_BUDGET_SCORES_PATH = EXPERIMENT_ROOT / "word_budget_external_validity_v1" / "scoring" / "response_scores.jsonl"
PRIMARY_RESULTS_PATH = EXPERIMENT_ROOT / "confirmatory_results.json"

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


def aggregate_budget_scores(path: Path, budget_field: str, neutral_only: bool) -> Dict[int, Dict[str, float]]:
    """Aggregate prose coverage and imbalance by one frozen budget coordinate."""
    grouped: Dict[int, Dict[str, List[float]]] = defaultdict(lambda: {"coverage": [], "imbalance": []})
    for row in read_jsonl(path):
        cell = row["cell"]
        if neutral_only and cell.get("affect") != "neutral":
            continue
        budget = int(cell[budget_field])
        prose = row["prose_selection"]
        grouped[budget]["coverage"].append(float(prose["total_material_coverage"]))
        grouped[budget]["imbalance"].append(float(prose["pairwise_absolute_imbalance"]))
    summaries: Dict[int, Dict[str, float]] = {}
    for budget, metrics in grouped.items():
        if len(metrics["coverage"]) != 210 or len(metrics["imbalance"]) != 210:
            raise ValueError(f"expected 210 neutral responses at budget {budget}")
        summaries[budget] = {name: float(np.mean(values)) for name, values in metrics.items()}
    return summaries


def load_budget_trajectories() -> Tuple[Dict[int, Dict[str, float]], Dict[int, Dict[str, float]]]:
    """Load exact and natural budget trajectories from the response scores."""
    exact = aggregate_budget_scores(EXACT_BUDGET_SCORES_PATH, "exact_fact_budget", neutral_only=True)
    natural = aggregate_budget_scores(WORD_BUDGET_SCORES_PATH, "word_budget", neutral_only=False)
    if sorted(exact) != [2, 4, 6] or sorted(natural) != [40, 80, 160]:
        raise ValueError("budget trajectories do not contain the complete frozen coordinate sets")
    if [round(natural[value]["coverage"], 3) for value in [40, 80, 160]] != [0.717, 0.891, 0.983]:
        raise ValueError("word-budget coverage does not match the Results table")
    if [round(natural[value]["imbalance"], 3) for value in [40, 80, 160]] != [0.305, 0.144, 0.035]:
        raise ValueError("word-budget imbalance does not match the Results table")
    if [round(exact[value]["coverage"], 3) for value in [2, 4]] != [0.442, 0.746]:
        raise ValueError("exact-budget coverage does not match the Results chapter")
    return exact, natural


def plot_budget_trajectories(exact: Dict[int, Dict[str, float]], natural: Dict[int, Dict[str, float]]) -> Path:
    """Plot prose coverage and imbalance across the two budget experiments."""
    figure, axes = plt.subplots(1, 2, figsize=(7.25, 3.7), sharey=True)
    panels = [
        (axes[0], exact, [2, 4, 6], "Exact fact budget", "Selected facts permitted"),
        (axes[1], natural, [40, 80, 160], "Natural word limit", "Maximum words requested"),
    ]
    for axis, data, budgets, title, xlabel in panels:
        coverage = [data[budget]["coverage"] for budget in budgets]
        imbalance = [data[budget]["imbalance"] for budget in budgets]
        axis.plot(budgets, coverage, color=NAVY, marker="o", linewidth=2.2, label="Coverage $T$")
        axis.plot(budgets, imbalance, color=CYAN, marker="s", linewidth=2.2, label="Imbalance $A$")
        axis.set_title(title, weight="bold")
        axis.set_xlabel(xlabel)
        axis.set_xticks(budgets)
        axis.set_ylim(0, 1.03)
        axis.grid(axis="y", color=LIGHT_GREY, linewidth=0.7)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Mean response-level score")
    axes[1].legend(loc="center right", frameon=False)
    figure.suptitle("More response space increases coverage and reduces pairwise imbalance", x=0.04, ha="left", weight="bold")
    figure.tight_layout(rect=(0, 0, 1, 0.91), w_pad=2.4)

    output = OUTPUT_DIRECTORY / "budget_trajectories.pdf"
    figure.savefig(output)
    plt.close(figure)
    return output


def main() -> None:
    """Generate and validate every result-derived dissertation figure."""
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    configure_plot_style()
    contrasts = load_commercial_contrasts()
    heatmap = commercial_heatmap_values(contrasts)
    effects = scenario_k2_effects(contrasts)
    domains = load_scenario_domains()
    exact, natural = load_budget_trajectories()
    outputs = [
        plot_primary_effects_forest(load_primary_results()),
        plot_commercial_heatmap(heatmap),
        plot_scenario_k2_effects(effects, domains),
        plot_budget_trajectories(exact, natural),
    ]
    for output in outputs:
        print(output.relative_to(REPOSITORY_ROOT))


if __name__ == "__main__":
    main()
