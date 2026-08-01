"""Generate paper-ready execution summaries without scoring model responses."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Iterable, List

from src.data_models.experiments import ConversationTranscript, RunOutcomeStatus


def _latex_escape(value: str) -> str:
    """Escape the small LaTeX-sensitive character set used in model identifiers."""
    return value.replace("\\", r"\textbackslash{}").replace("_", r"\_").replace("&", r"\&").replace("%", r"\%")


def _transcript_cost(transcript: ConversationTranscript) -> Decimal:
    """Sum provider-reported billed credits across all successful attempts."""
    costs = [attempt.usage.cost_credits for attempt in [*transcript.initial_attempts, *transcript.follow_up_attempts] if attempt.usage is not None]
    return sum((cost for cost in costs if cost is not None), Decimal("0"))


def _retry_count(transcript: ConversationTranscript) -> int:
    """Count attempts beyond the first attempt for each requested assistant turn."""
    initial_retries = max(0, len(transcript.initial_attempts) - 1)
    follow_up_retries = max(0, len(transcript.follow_up_attempts) - 1)
    return initial_retries + follow_up_retries


def generate_response_paper_assets(
    transcripts: Iterable[ConversationTranscript],
    output_dir: Path,
    experiment_name: str,
) -> Path:
    """Write a stable LaTeX table of terminal response-generation outcomes by model."""
    records = list(transcripts)
    output_dir.mkdir(parents=True, exist_ok=True)
    model_ids = sorted({transcript.run_unit.model_id for transcript in records})
    lines: List[str] = [
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"Model & Terminal & Completed & Retries & Cost credits \\",
        r"\midrule",
    ]
    for model_id in model_ids:
        selected = [transcript for transcript in records if transcript.run_unit.model_id == model_id]
        completed = sum(transcript.outcome_status == RunOutcomeStatus.COMPLETED for transcript in selected)
        retries = sum(_retry_count(transcript) for transcript in selected)
        cost = sum((_transcript_cost(transcript) for transcript in selected), Decimal("0"))
        lines.append(f"{_latex_escape(model_id)} & {len(selected)} & {completed} & {retries} & {cost:.6f} \\\\")
    lines.extend([r"\bottomrule", r"\end{tabular}", ""])
    output_path = output_dir / f"{experiment_name}_table.tex"
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
