"""Generate stable paper-ready assets from experiment scoring outputs."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from src.data_models.experiments import ScoredRunRecord
from src.experiments.io import read_jsonl_models, result_paths


def load_scored_records(experiment_dir: Path) -> List[ScoredRunRecord]:
    """Load all scored run records from an experiment directory."""
    records: List[ScoredRunRecord] = []
    for path in result_paths(experiment_dir=experiment_dir, pattern="*_scoring_results.jsonl"):
        records.extend(read_jsonl_models(path=path, model=ScoredRunRecord))
    return records


def mean(values: List[float]) -> float:
    """Return the arithmetic mean, using zero for empty inputs."""
    if not values:
        return 0.0
    return sum(values) / float(len(values))


def escape_latex(value: str) -> str:
    """Escape a compact subset of LaTeX-sensitive characters in table cells."""
    return (
        value.replace("\\", "\\textbackslash{}")
        .replace("_", "\\_")
        .replace("&", "\\&")
        .replace("%", "\\%")
        .replace("#", "\\#")
    )


def format_float(value: float) -> str:
    """Format a metric value for a LaTeX table."""
    return f"{value:.3f}"


def format_summary_metric(metrics: Dict[str, float], metric: str) -> str:
    """Format an aggregate metric or show an explicit unavailable marker."""
    if metric not in metrics:
        return "--"
    return format_float(metrics[metric])


def summarize_by_model_prompt_and_persona(
    records: List[ScoredRunRecord],
) -> Dict[Tuple[str, str, str], Dict[str, float]]:
    """Aggregate metrics without collapsing the experimental persona factor."""
    grouped: Dict[Tuple[str, str, str], Dict[str, List[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for record in records:
        key = (
            record.run_unit.agent_model_id,
            record.run_unit.prompt_condition.value,
            record.run_unit.persona_id.value,
        )
        grouped[key]["unsupported_or_false"].append(record.response_metrics.false_claim_score)
        grouped[key]["initial_omission"].append(
            record.response_metrics.initial_primary_omission_score
        )
        grouped[key]["persistent_omission"].append(
            record.response_metrics.persistent_primary_omission_score
        )
        if record.response_metrics.repair_rate is not None:
            grouped[key]["repair"].append(record.response_metrics.repair_rate)
        grouped[key]["initial_understatement"].append(
            record.response_metrics.initial_understatement_rate
        )
        grouped[key]["post_understatement"].append(
            record.response_metrics.post_followup_understatement_rate
        )
        grouped[key]["specificity_loss"].append(
            record.response_metrics.initial_primary_specificity_loss_score
        )
        grouped[key]["favorable_disclosure"].append(
            record.response_metrics.favorable_control_disclosure_rate
        )
        grouped[key]["neutral_disclosure"].append(
            record.response_metrics.neutral_control_disclosure_rate
        )
        grouped[key]["false_claim_count"].append(float(record.response_metrics.false_claim_count))
        grouped[key]["exploratory_composite"].append(
            record.response_metrics.exploratory_equal_weight_composite
        )
        if record.user_harm_metrics is not None:
            grouped[key]["harmful_action"].append(
                1.0 if record.user_harm_metrics.harmful_action_selected else 0.0
            )
            grouped[key]["unsupported_belief"].append(
                record.user_harm_metrics.unsupported_belief_rate
            )
            grouped[key]["partial_or_unsupported_belief"].append(
                record.user_harm_metrics.partial_or_unsupported_belief_rate
            )

    return {
        key: {metric: mean(values) for metric, values in metrics.items()}
        for key, metrics in grouped.items()
    }


def render_latex_summary_table(experiment_name: str, records: List[ScoredRunRecord]) -> str:
    """Render a stable LaTeX tabular summary for scored experiment outputs."""
    summary = summarize_by_model_prompt_and_persona(records)
    return render_current_latex_summary_table(experiment_name=experiment_name, summary=summary)


def render_current_latex_summary_table(
    experiment_name: str,
    summary: Dict[Tuple[str, str, str], Dict[str, float]],
) -> str:
    """Render headline, control, and false-claim metrics without collapsing persona."""
    headline_rows = []
    diagnostic_rows = []
    user_outcome_rows = []
    for (model_id, prompt_condition, persona_id), metrics in sorted(summary.items()):
        identity = [
            escape_latex(model_id),
            escape_latex(prompt_condition),
            escape_latex(persona_id),
        ]
        headline_rows.append(
            " & ".join(
                identity
                + [
                    format_float(metrics.get("initial_omission", 0.0)),
                    format_float(metrics.get("persistent_omission", 0.0)),
                    format_summary_metric(metrics, "repair"),
                    format_float(metrics.get("initial_understatement", 0.0)),
                    format_float(metrics.get("post_understatement", 0.0)),
                    format_float(metrics.get("specificity_loss", 0.0)),
                    format_float(metrics.get("exploratory_composite", 0.0)),
                ]
            )
            + r" \\"
        )
        diagnostic_rows.append(
            " & ".join(
                identity
                + [
                    format_float(metrics.get("favorable_disclosure", 0.0)),
                    format_float(metrics.get("neutral_disclosure", 0.0)),
                    format_float(metrics.get("unsupported_or_false", 0.0)),
                    format_float(metrics.get("false_claim_count", 0.0)),
                ]
            )
            + r" \\"
        )
        user_outcome_rows.append(
            " & ".join(
                identity
                + [
                    format_summary_metric(metrics, "harmful_action"),
                    format_summary_metric(metrics, "unsupported_belief"),
                    format_summary_metric(metrics, "partial_or_unsupported_belief"),
                ]
            )
            + r" \\"
        )
    headline_body = (
        "\n".join(headline_rows)
        if headline_rows
        else r"\multicolumn{10}{l}{No scored records available.} \\"
    )
    diagnostic_body = (
        "\n".join(diagnostic_rows)
        if diagnostic_rows
        else r"\multicolumn{7}{l}{No scored records available.} \\"
    )
    user_outcome_body = (
        "\n".join(user_outcome_rows)
        if user_outcome_rows
        else r"\multicolumn{6}{l}{No scored records available.} \\"
    )
    return "\n".join(
        [
            r"\begin{tabular}{lllrrrrrrr}",
            r"\toprule",
            (
                r"Model & Prompt & Persona & Initial omit. & Persistent omit. & Repair & "
                r"Initial understate & Post understate & Specificity loss & "
                r"Exploratory composite \\"
            ),
            r"\midrule",
            headline_body,
            r"\bottomrule",
            r"\end{tabular}",
            "",
            r"\begin{tabular}{lllrrrr}",
            r"\toprule",
            r"Model & Prompt & Persona & Favorable disclose. & Neutral disclose. & False claim & False claim count \\",
            r"\midrule",
            diagnostic_body,
            r"\bottomrule",
            r"\end{tabular}",
            "",
            r"\begin{tabular}{lllrrr}",
            r"\toprule",
            (
                r"Model & Prompt & Persona & Harmful action & Unsupported belief & "
                r"Partial/unsupported belief \\"
            ),
            r"\midrule",
            user_outcome_body,
            r"\bottomrule",
            r"\end{tabular}",
            f"% Generated from {escape_latex(experiment_name)} scored outputs.",
        ]
    )


def generate_paper_assets(experiment_dir: Path) -> Path:
    """Generate the stable LaTeX summary table for an experiment."""
    experiment_name = experiment_dir.name
    records = load_scored_records(experiment_dir)
    assets_dir = experiment_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    table_path = assets_dir / f"{experiment_name}_table.tex"
    table_path.write_text(
        render_latex_summary_table(experiment_name=experiment_name, records=records),
        encoding="utf-8",
    )
    return table_path
