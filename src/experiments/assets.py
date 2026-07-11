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


def summarize_by_model_and_prompt(
    records: List[ScoredRunRecord],
) -> Dict[Tuple[str, str], Dict[str, float]]:
    """Aggregate headline metrics by agent model and prompt condition."""
    grouped: Dict[Tuple[str, str], Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    for record in records:
        key = (
            record.run_unit.agent_model_id,
            record.run_unit.prompt_condition.value,
        )
        grouped[key]["deception"].append(
            record.response_metrics.materiality_weighted_deception_score
        )
        grouped[key]["adverse_omission"].append(record.response_metrics.adverse_omission_score)
        grouped[key]["false_claim"].append(record.response_metrics.false_claim_score)
        if record.user_harm_metrics is not None:
            grouped[key]["harmful_action"].append(
                1.0 if record.user_harm_metrics.harmful_action_selected else 0.0
            )

    return {
        key: {metric: mean(values) for metric, values in metrics.items()}
        for key, metrics in grouped.items()
    }


def render_latex_summary_table(experiment_name: str, records: List[ScoredRunRecord]) -> str:
    """Render a stable LaTeX tabular summary for scored experiment outputs."""
    summary = summarize_by_model_and_prompt(records)
    rows = []
    for (model_id, prompt_condition), metrics in sorted(summary.items()):
        rows.append(
            " & ".join(
                [
                    escape_latex(model_id),
                    escape_latex(prompt_condition),
                    format_float(metrics.get("deception", 0.0)),
                    format_float(metrics.get("adverse_omission", 0.0)),
                    format_float(metrics.get("false_claim", 0.0)),
                    format_float(metrics.get("harmful_action", 0.0)),
                ]
            )
            + r" \\"
        )
    body = "\n".join(rows) if rows else r"\multicolumn{6}{l}{No scored records available.} \\"
    return "\n".join(
        [
            r"\begin{tabular}{llrrrr}",
            r"\toprule",
            r"Model & Prompt & Deception & Omission & False claim & Harmful action \\",
            r"\midrule",
            body,
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
