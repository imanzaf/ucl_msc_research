"""Audit frozen judge outputs for structural and semantic-consistency anomalies."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Literal, Optional, Sequence, Set, Tuple

from pydantic import Field

from src.common import ImmutableModel
from src.experiments.accounting import load_run_caches
from src.models.enums import JudgeContract
from src.models.scoring import AccuracyJudgeOutput, AdjudicatedJudgment, ContentJudgeOutput, JudgeTask, PresentationJudgeOutput
from src.paths import experiment_paths, scoring_paths
from src.scoring.judges import response_text_for_scoring
from src.storage import read_jsonl, write_json, write_jsonl

SCHEMA_VERSION = "4.0.0"
ACTIVE_EXPERIMENTS = (
    "commercial_interest_instruction_v1",
    "information_budget_v1",
    "option_first_v1",
    "ownership_role_control_v1",
    "single_fact_priority_v1",
    "user_state_adaptation_v2",
    "word_budget_external_validity_v1",
)
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "may",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "would",
    "you",
    "your",
}
NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:[£$]\s*)?\d+(?:[.,]\d+)*(?:\s*(?:%|bps?|years?|months?|days?|hours?|minutes?|words?))?", re.IGNORECASE
)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?", re.IGNORECASE)


class AuditFinding(ImmutableModel):
    """Describe one deterministic reason that a final judgment merits inspection."""

    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^4\.0\.0$")
    experiment: str
    judge_call_id: str
    run_unit_id: str
    contract: JudgeContract
    fact_id: Optional[str]
    severity: Literal["high", "medium"]
    check: str
    detail: str
    response_text: str
    candidate_fact_text: Optional[str] = None
    anchor: Optional[str] = None
    final_output: Dict[str, object]


class AuditSummary(ImmutableModel):
    """Summarize exhaustive audit coverage and diagnostic findings."""

    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^4\.0\.0$")
    experiments: List[str]
    response_count: int
    judgment_count: int
    contract_counts: Dict[str, int]
    finding_count: int
    findings_by_severity: Dict[str, int]
    findings_by_check: Dict[str, int]


def _normalize(text: str) -> str:
    """Normalize punctuation and whitespace for conservative exact-meaning checks."""
    lowered = text.casefold().replace("–", "-").replace("—", "-")
    return " ".join(TOKEN_PATTERN.findall(lowered))


def _tokens(text: str) -> Set[str]:
    """Return non-trivial lexical tokens for overlap diagnostics."""
    return {token for token in TOKEN_PATTERN.findall(text.casefold()) if token not in STOP_WORDS and len(token) > 2}


def _numbers(text: str) -> Set[str]:
    """Return normalized explicit quantities from text."""
    return {re.sub(r"\s+", "", match.group(0).casefold()).replace(",", "") for match in NUMBER_PATTERN.finditer(text)}


def _payload(task: JudgeTask) -> Dict[str, object]:
    """Decode the exact case payload supplied to a frozen judge call."""
    return json.loads(task.messages[1]["content"])


def _finding(
    experiment: str,
    task: JudgeTask,
    judgment: AdjudicatedJudgment,
    severity: Literal["high", "medium"],
    check: str,
    detail: str,
    payload: Dict[str, object],
) -> AuditFinding:
    """Build one finding with the complete frozen evidence needed for review."""
    return AuditFinding(
        experiment=experiment,
        judge_call_id=task.judge_call_id,
        run_unit_id=task.run_unit_id,
        contract=task.contract,
        fact_id=task.fact_id,
        severity=severity,
        check=check,
        detail=detail,
        response_text=str(payload["response_text"]),
        candidate_fact_text=str(payload["candidate_fact_text"]) if "candidate_fact_text" in payload else None,
        anchor=str(payload["anchor"]) if "anchor" in payload else None,
        final_output=judgment.output.model_dump(mode="json"),
    )


def _content_findings(
    experiment: str,
    task: JudgeTask,
    judgment: AdjudicatedJudgment,
    payload: Dict[str, object],
) -> List[AuditFinding]:
    """Flag conservative content-label and anchor inconsistencies."""
    output = judgment.output
    if not isinstance(output, ContentJudgeOutput):
        raise TypeError("content task has a non-content final output")
    response = str(payload["response_text"])
    candidate = str(payload["candidate_fact_text"])
    anchor = str(payload["anchor"])
    findings: List[AuditFinding] = []
    response_normalized = _normalize(response)
    anchor_normalized = _normalize(anchor)
    candidate_tokens = _tokens(candidate)
    candidate_numbers = _numbers(candidate)

    if not output.fact_present:
        if anchor_normalized and anchor_normalized in response_normalized:
            findings.append(
                _finding(
                    experiment,
                    task,
                    judgment,
                    "high",
                    "absent_fact_contains_exact_anchor",
                    "The response contains the candidate anchor verbatim after normalization although the fact is labelled absent.",
                    payload,
                )
            )
        response_tokens = _tokens(response)
        overlap = candidate_tokens & response_tokens
        if candidate_numbers and candidate_numbers.issubset(_numbers(response)) and len(overlap) >= 4:
            findings.append(
                _finding(
                    experiment,
                    task,
                    judgment,
                    "medium",
                    "absent_fact_contains_quantity_and_terms",
                    f"All candidate quantities and {len(overlap)} substantive candidate tokens occur in the response.",
                    payload,
                )
            )
        return findings

    excerpt = output.supporting_excerpt or ""
    if excerpt not in response:
        findings.append(
            _finding(
                experiment,
                task,
                judgment,
                "high",
                "present_fact_excerpt_not_exact",
                "The supporting excerpt is not an exact substring of the scored response.",
                payload,
            )
        )
    overlap = candidate_tokens & _tokens(excerpt)
    if candidate_tokens and not overlap:
        findings.append(
            _finding(
                experiment,
                task,
                judgment,
                "medium",
                "present_fact_zero_lexical_overlap",
                "The supporting excerpt and candidate fact share no substantive lexical token; a semantic paraphrase check is required.",
                payload,
            )
        )
    excerpt_normalized = _normalize(excerpt)
    if not output.anchor_present and anchor_normalized and anchor_normalized in excerpt_normalized:
        findings.append(
            _finding(
                experiment,
                task,
                judgment,
                "high",
                "anchor_label_false_with_exact_anchor",
                "The supporting excerpt contains the complete candidate anchor although anchor_present is false.",
                payload,
            )
        )
    anchor_numbers = _numbers(anchor)
    if output.anchor_present and anchor_numbers and not anchor_numbers.issubset(_numbers(excerpt)):
        findings.append(
            _finding(
                experiment,
                task,
                judgment,
                "medium",
                "anchor_label_true_without_anchor_quantity",
                "The anchor is numerical, but its explicit quantity does not occur in the supporting excerpt.",
                payload,
            )
        )
    return findings


def _presentation_findings(
    experiment: str,
    task: JudgeTask,
    judgment: AdjudicatedJudgment,
    payload: Dict[str, object],
) -> List[AuditFinding]:
    """Flag presentation labels that conflict with unambiguous surface order."""
    output = judgment.output
    if not isinstance(output, PresentationJudgeOutput):
        raise TypeError("presentation task has a non-presentation final output")
    response = str(payload["response_text"])
    option_a = str(payload["option_a_name"])
    option_b = str(payload["option_b_name"])
    response_lower = response.casefold()
    position_a = response_lower.find(option_a.casefold())
    position_b = response_lower.find(option_b.casefold())
    if position_a < 0 or position_b < 0 or position_a == position_b:
        return []
    expected = "option_a" if position_a < position_b else "option_b"
    if output.option_presented_first.value == expected:
        return []
    return [
        _finding(
            experiment,
            task,
            judgment,
            "medium",
            "presentation_order_surface_mismatch",
            f"The first exact option-name occurrence suggests {expected}, while the final label is {output.option_presented_first.value}.",
            payload,
        )
    ]


def _accuracy_findings(
    experiment: str,
    task: JudgeTask,
    judgment: AdjudicatedJudgment,
    payload: Dict[str, object],
) -> List[AuditFinding]:
    """Flag exact-evidence and numerical-status inconsistencies in accuracy labels."""
    output = judgment.output
    if not isinstance(output, AccuracyJudgeOutput):
        raise TypeError("accuracy task has a non-accuracy final output")
    response = str(payload["response_text"])
    findings: List[AuditFinding] = []
    for issue in output.issues:
        if issue.evidence not in response:
            findings.append(
                _finding(
                    experiment,
                    task,
                    judgment,
                    "high",
                    "accuracy_evidence_not_exact",
                    "An accuracy issue's evidence is not an exact substring of the scored response.",
                    payload,
                )
            )
        evidence_has_quantity = bool(_numbers(issue.evidence))
        if issue.numerical != evidence_has_quantity:
            findings.append(
                _finding(
                    experiment,
                    task,
                    judgment,
                    "medium",
                    "accuracy_numerical_flag_mismatch",
                    f"The issue numerical flag is {issue.numerical}, while deterministic quantity detection is {evidence_has_quantity}.",
                    payload,
                )
            )
    return findings


def _audit_experiment(experiment: str) -> Tuple[List[AuditFinding], Counter[str], int]:
    """Audit every final judgment in one experiment and require an exact task join."""
    paths = scoring_paths(experiment)
    tasks = [JudgeTask.model_validate(record) for record in read_jsonl(paths["judge_plan"])]
    judgments = [AdjudicatedJudgment.model_validate(record) for record in read_jsonl(paths["final_judgments"])]
    task_by_id = {task.judge_call_id: task for task in tasks}
    judgment_by_id = {judgment.judge_call_id: judgment for judgment in judgments}
    runs = load_run_caches([experiment_paths(experiment)["cache"]])
    response_text_by_run = {run.run_unit_id: response_text_for_scoring(run) for run in runs}
    if len(task_by_id) != len(tasks) or len(judgment_by_id) != len(judgments) or set(task_by_id) != set(judgment_by_id):
        raise ValueError(f"{experiment} does not have a unique exact task-to-final-judgment join")
    findings: List[AuditFinding] = []
    contract_counts: Counter[str] = Counter()
    response_ids: Set[str] = set()
    for task in tasks:
        judgment = judgment_by_id[task.judge_call_id]
        if (task.run_unit_id, task.contract, task.fact_id) != (judgment.run_unit_id, judgment.contract, judgment.fact_id):
            raise ValueError(f"{experiment} has a mismatched final judgment coordinate")
        payload = _payload(task)
        payload["response_text"] = response_text_by_run[task.run_unit_id]
        contract_counts[task.contract.value] += 1
        response_ids.add(task.run_unit_id)
        if task.contract == JudgeContract.CONTENT:
            findings.extend(_content_findings(experiment, task, judgment, payload))
        elif task.contract == JudgeContract.PRESENTATION:
            findings.extend(_presentation_findings(experiment, task, judgment, payload))
        else:
            findings.extend(_accuracy_findings(experiment, task, judgment, payload))
    return findings, contract_counts, len(response_ids)


def audit(experiments: Sequence[str]) -> Tuple[List[AuditFinding], AuditSummary]:
    """Run all deterministic diagnostics and return findings with coverage totals."""
    findings: List[AuditFinding] = []
    contract_counts: Counter[str] = Counter()
    response_count = 0
    for experiment in experiments:
        experiment_findings, experiment_counts, experiment_responses = _audit_experiment(experiment)
        findings.extend(experiment_findings)
        contract_counts.update(experiment_counts)
        response_count += experiment_responses
    summary = AuditSummary(
        experiments=list(experiments),
        response_count=response_count,
        judgment_count=sum(contract_counts.values()),
        contract_counts=dict(sorted(contract_counts.items())),
        finding_count=len(findings),
        findings_by_severity=dict(sorted(Counter(finding.severity for finding in findings).items())),
        findings_by_check=dict(sorted(Counter(finding.check for finding in findings).items())),
    )
    return findings, summary


def main() -> None:
    """Run the read-only audit and write a diagnostic bundle outside frozen artifacts."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiments", nargs="+", choices=ACTIVE_EXPERIMENTS, default=list(ACTIVE_EXPERIMENTS))
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    findings, summary = audit(args.experiments)
    args.output_root.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_root / "findings.jsonl", findings)
    write_json(args.output_root / "summary.json", summary)
    print(json.dumps(summary.model_dump(mode="json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
