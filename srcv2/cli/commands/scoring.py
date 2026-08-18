"""Three-judge prompt development, execution, freezing, and adjudication commands."""

from __future__ import annotations

import argparse
import threading
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import List

from srcv2.common import artifact_sha256, utc_now
from srcv2.experiments.accounting import load_run_caches
from srcv2.llm.openrouter import OpenRouterClient
from srcv2.models.catalog import load_model_catalog
from srcv2.models.enums import CommercialInterestTask, ExperimentKind, JudgeContract, JudgeStage
from srcv2.models.experiments import CommercialInterestCell, InformationBudgetCell, RunUnit
from srcv2.models.manifests import ProtocolManifest
from srcv2.models.queries import QueryVariant
from srcv2.models.scenarios import AcceptedScenario
from srcv2.models.scoring import (
    AdjudicatedJudgment,
    ExperimentScoringManifest,
    FrozenJudgeContract,
    JudgeCallRecord,
    JudgeExecutionApproval,
    JudgeExecutionEstimate,
    JudgeOverride,
    JudgePilotSample,
    JudgeTask,
    SelectionRecoveryRecord,
)
from srcv2.paths import EXPERIMENT_ROOT, SCENARIO_ROOT, experiment_paths, scoring_paths
from srcv2.scoring.aggregation import score_responses
from srcv2.scoring.execution import (
    adjudicate_judgments,
    build_execution_approval,
    build_execution_estimate,
    execute_judge_batch,
    freeze_judge_contract,
    judge_plan_sha256,
    merge_judge_records,
    validate_full_plan,
)
from srcv2.scoring.judges import build_judge_plan, judge_controls, judge_prompt_summary, response_text_for_scoring
from srcv2.scoring.pilot import build_pilot_sample, build_sampling_frame
from srcv2.scoring.selections import recover_selection_records
from srcv2.settings import CredentialRole, get_api_settings, get_model_settings
from srcv2.storage import read_json, read_jsonl, write_json, write_jsonl

PROTOCOL_MANIFEST = EXPERIMENT_ROOT / "final_protocol_manifest.json"
SCORING_EXPERIMENTS = tuple(kind.value for kind in ExperimentKind if kind != ExperimentKind.BALANCED_PROMINENCE)


def _add_experiment_argument(parser: argparse.ArgumentParser) -> None:
    """Require one active experiment for every scoring operation."""
    parser.add_argument("--experiment", choices=SCORING_EXPERIMENTS, required=True)


def _ensure_layout(experiment: str) -> dict[str, Path]:
    """Create and return one experiment's self-contained scoring layout."""
    paths = scoring_paths(experiment)
    for name in ("root", "cache", "logs", "checkpoints"):
        paths[name].mkdir(parents=True, exist_ok=True)
    return paths


def _experiment_runs(experiment: str) -> list[RunUnit]:
    """Load completed evaluated responses for one named experiment."""
    runs = load_run_caches([experiment_paths(experiment)["cache"]])
    expected = ExperimentKind(experiment)
    if not runs or any(run.experiment != expected for run in runs):
        raise ValueError(f"response cache does not contain only {experiment}")
    return runs


def _scenarios(path: Path) -> List[AcceptedScenario]:
    """Load the accepted six-fact scenario corpus."""
    return [AcceptedScenario.model_validate(record) for record in read_jsonl(path)]


def _queries(path: Path) -> List[QueryVariant]:
    """Load the accepted customer-query variants."""
    return [QueryVariant.model_validate(record) for record in read_jsonl(path)]


def _sample_pilot(arguments: List[str]) -> None:
    """Draw and freeze one experiment's stratified five-percent judge-development sample."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring sample-pilot")
    _add_experiment_argument(parser)
    parser.add_argument("--seed", type=int, default=410191)
    parser.add_argument("--sample-size", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(arguments)
    paths = _ensure_layout(args.experiment)
    output = args.output or paths["pilot_sample"]
    sample = build_pilot_sample(build_sampling_frame(_experiment_runs(args.experiment)), sample_size=args.sample_size, random_seed=args.seed)
    write_json(output, sample)
    print(f"Wrote {len(sample.response_ids)} judge-development response identifiers to {output}")


def _show_prompts(arguments: List[str]) -> None:
    """Write the three exact prompts, schemas, hashes, and output ceilings for review."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring show-prompts")
    _add_experiment_argument(parser)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(arguments)
    paths = _ensure_layout(args.experiment)
    output = args.output or paths["judge_prompts"]
    write_json(
        output,
        {
            "schema_version": "4.0.0",
            "experiment": args.experiment,
            "judge_model_slug": load_model_catalog().scoring_model.model_slug,
            "judges": judge_prompt_summary(),
        },
    )
    print(f"Wrote three reviewable judge contracts to {output}")


def _recover_selections(arguments: List[str]) -> None:
    """Recover unambiguous exact-budget selections without changing response adherence."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring recover-selections")
    _add_experiment_argument(parser)
    parser.add_argument("--scenarios", type=Path, default=SCENARIO_ROOT / "accepted_scenarios.jsonl")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args(arguments)
    paths = _ensure_layout(args.experiment)
    output = args.output or paths["selections"]
    summary = args.summary or paths["logs"] / "selection_summary.json"
    runs = [
        run
        for run in _experiment_runs(args.experiment)
        if isinstance(run.cell, InformationBudgetCell)
        or (isinstance(run.cell, CommercialInterestCell) and run.cell.task == CommercialInterestTask.EXACT_BUDGET)
    ]
    if not runs:
        raise ValueError(f"{args.experiment} has no exact-budget responses")
    run_by_id = {run.run_unit_id: run for run in runs}
    records: List[SelectionRecoveryRecord] = recover_selection_records(runs, _scenarios(args.scenarios))
    if len(records) != len(runs):
        raise ValueError("selection recovery must produce one record per exact-budget response")
    write_jsonl(output, records)
    counts = Counter(record.source for record in records)
    by_model = {
        model_slug: dict(Counter(record.source for record in records if run_by_id[record.run_unit_id].model.model_slug == model_slug))
        for model_slug in sorted({run.model.model_slug for run in runs})
    }
    by_experiment = {
        experiment.value: dict(Counter(record.source for record in records if run_by_id[record.run_unit_id].experiment == experiment))
        for experiment in sorted({run.experiment for run in runs}, key=lambda item: item.value)
    }
    write_json(
        summary,
        {
            "schema_version": "4.0.0",
            "response_count": len(records),
            "usable_selection_count": sum(record.selection_usable for record in records),
            "format_adherent_count": sum(record.format_adherent for record in records),
            "by_source": dict(counts),
            "by_model": by_model,
            "by_experiment": by_experiment,
        },
    )
    print(f"Wrote {len(records)} selection records to {output}: " + ", ".join(f"{source}={count}" for source, count in sorted(counts.items())))


def _build_plan(arguments: List[str]) -> None:
    """Build a complete or one-contract judge plan for the pilot or frozen corpus."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring build-plan")
    _add_experiment_argument(parser)
    parser.add_argument("--stage", choices=[stage.value for stage in JudgeStage], required=True)
    parser.add_argument("--contract", choices=[contract.value for contract in JudgeContract])
    parser.add_argument("--pilot-sample", type=Path)
    parser.add_argument("--scenarios", type=Path, default=SCENARIO_ROOT / "accepted_scenarios.jsonl")
    parser.add_argument("--queries", type=Path, default=SCENARIO_ROOT / "query_variants.jsonl")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(arguments)
    paths = _ensure_layout(args.experiment)
    stage = JudgeStage(args.stage)
    response_ids = None
    if stage == JudgeStage.PILOT:
        pilot_sample = args.pilot_sample or paths["pilot_sample"]
        response_ids = JudgePilotSample.model_validate(read_json(pilot_sample)).response_ids
    runs = _experiment_runs(args.experiment)
    tasks = build_judge_plan(runs, _scenarios(args.scenarios), _queries(args.queries), stage, response_ids)
    response_count = len(response_ids) if response_ids is not None else len(runs)
    if args.contract is not None:
        contract = JudgeContract(args.contract)
        tasks = [task for task in tasks if task.contract == contract]
        calls_per_response = 6 if contract == JudgeContract.CONTENT else 1
    else:
        calls_per_response = 8
    expected = response_count * calls_per_response
    if len(tasks) != expected:
        raise ValueError(f"{stage.value} judge plan requires exactly {expected} calls")
    output = args.output or (paths["pilot_plan"] if stage == JudgeStage.PILOT else paths["judge_plan"])
    write_jsonl(output, tasks)
    print(f"Wrote {len(tasks)} judge calls with plan hash {judge_plan_sha256(tasks)}")


def _merge_results(arguments: List[str]) -> None:
    """Merge reusable and replacement raw records into one ordered plan result."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring merge-results")
    _add_experiment_argument(parser)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(arguments)
    paths = _ensure_layout(args.experiment)
    plan = args.plan or paths["judge_plan"]
    output = args.output or paths["raw_results"]
    tasks = [JudgeTask.model_validate(record) for record in read_jsonl(plan)]
    record_sets = [[JudgeCallRecord.model_validate(record) for record in read_jsonl(path)] for path in args.source]
    records = merge_judge_records(tasks, record_sets)
    write_jsonl(output, records)
    print(f"Wrote {len(records)} ordered raw judge records from {len(record_sets)} sources")


def _estimate_cost(arguments: List[str]) -> None:
    """Estimate the exact judge plan using caller-supplied current token prices."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring estimate-cost")
    _add_experiment_argument(parser)
    parser.add_argument("--stage", choices=[stage.value for stage in JudgeStage], default=JudgeStage.FULL.value)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--protocol-manifest", type=Path, default=PROTOCOL_MANIFEST)
    parser.add_argument("--input-price-per-million", type=Decimal, required=True)
    parser.add_argument("--output-price-per-million", type=Decimal, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(arguments)
    paths = _ensure_layout(args.experiment)
    stage = JudgeStage(args.stage)
    plan = args.plan or (paths["pilot_plan"] if stage == JudgeStage.PILOT else paths["judge_plan"])
    output = args.output or (paths["pilot_cost_estimate"] if stage == JudgeStage.PILOT else paths["cost_estimate"])
    tasks = [JudgeTask.model_validate(record) for record in read_jsonl(plan)]
    manifest = ProtocolManifest.model_validate(read_json(args.protocol_manifest))
    controls = manifest.generation_controls[manifest.scorer_model.model_slug]
    estimate = build_execution_estimate(tasks, controls, args.input_price_per_million, args.output_price_per_million)
    write_json(output, estimate)
    print(estimate.model_dump_json(indent=2))


def _approve_execution(arguments: List[str]) -> None:
    """Record bounded authorization for one exact pilot or full judge plan."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring approve-execution")
    _add_experiment_argument(parser)
    parser.add_argument("--stage", choices=[stage.value for stage in JudgeStage], default=JudgeStage.FULL.value)
    parser.add_argument("--estimate", type=Path)
    parser.add_argument("--approved-max-cost", type=Decimal, required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--confirm-paid-execution", action="store_true", required=True)
    args = parser.parse_args(arguments)
    paths = _ensure_layout(args.experiment)
    stage = JudgeStage(args.stage)
    estimate_path = args.estimate or (paths["pilot_cost_estimate"] if stage == JudgeStage.PILOT else paths["cost_estimate"])
    output = args.output or (paths["pilot_approval"] if stage == JudgeStage.PILOT else paths["approval"])
    estimate = JudgeExecutionEstimate.model_validate(read_json(estimate_path))
    approval = build_execution_approval(estimate, args.approved_max_cost, args.approved_by, args.note)
    write_json(output, approval)
    print(f"Wrote judge execution approval {approval.approval_sha256}")


def _execute(arguments: List[str], stage: JudgeStage) -> None:
    """Execute or resume one approved pilot or frozen full judge plan."""
    parser = argparse.ArgumentParser(prog=f"risk-comm-v2 scoring execute-{stage.value}")
    _add_experiment_argument(parser)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--protocol-manifest", type=Path, default=PROTOCOL_MANIFEST)
    parser.add_argument("--estimate", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--frozen-contract", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--max-workers", type=int, default=8)
    args = parser.parse_args(arguments)
    paths = _ensure_layout(args.experiment)
    if stage == JudgeStage.PILOT:
        plan_path = args.plan or paths["pilot_plan"]
        estimate_path = args.estimate or paths["pilot_cost_estimate"]
        approval_path = args.approval or paths["pilot_approval"]
        cache_dir = args.cache_dir or paths["cache"] / "pilot"
        output = args.output or paths["pilot_raw_results"]
        summary = args.summary or paths["logs"] / "pilot_summary.json"
    else:
        plan_path = args.plan or paths["judge_plan"]
        estimate_path = args.estimate or paths["cost_estimate"]
        approval_path = args.approval or paths["approval"]
        cache_dir = args.cache_dir or paths["cache"] / "full"
        output = args.output or paths["raw_results"]
        summary = args.summary or paths["summary"]
    tasks = [JudgeTask.model_validate(record) for record in read_jsonl(plan_path)]
    if not tasks or any(task.stage != stage for task in tasks):
        raise ValueError(f"execute-{stage.value} requires a {stage.value}-only judge plan")
    manifest = ProtocolManifest.model_validate(read_json(args.protocol_manifest))
    base_controls = manifest.generation_controls[manifest.scorer_model.model_slug]
    if stage == JudgeStage.FULL:
        frozen_contract = args.frozen_contract or paths["frozen_contract"]
        contract = FrozenJudgeContract.model_validate(read_json(frozen_contract))
        validate_full_plan(tasks, contract)
        if contract.judge_model != manifest.scorer_model:
            raise PermissionError("frozen contract and protocol manifest use different judge models")
        expected_controls = {judge: contract.generation_controls[judge] for judge in contract.generation_controls}
        if expected_controls != {judge: judge_controls(base_controls, judge) for judge in expected_controls}:
            raise PermissionError("current judge controls differ from the frozen contract")
    estimate = JudgeExecutionEstimate.model_validate(read_json(estimate_path))
    approval = JudgeExecutionApproval.model_validate(read_json(approval_path))
    thread_local = threading.local()

    def client_factory() -> OpenRouterClient:
        """Return one scoring client owned by the current worker thread."""
        client = getattr(thread_local, "client", None)
        if client is None:
            client = OpenRouterClient.from_settings(get_api_settings(), get_model_settings(), CredentialRole.SCORING)
            thread_local.client = client
        return client

    def report(completed: int, total: int, record: JudgeCallRecord) -> None:
        """Print sparse progress without exposing prompts or response text."""
        if completed == total or completed % 100 == 0:
            print(f"judge calls completed: {completed}/{total}; latest={record.judge_call_id}")

    records = execute_judge_batch(
        tasks,
        manifest.scorer_model,
        base_controls,
        client_factory,
        estimate,
        approval,
        cache_dir,
        max_workers=args.max_workers,
        progress=report,
    )
    write_jsonl(output, records)
    billed_cost = sum((record.billed_cost or Decimal(0) for record in records), Decimal(0))
    write_json(
        summary,
        {
            "schema_version": "4.0.0",
            "stage": stage.value,
            "judge_plan_sha256": judge_plan_sha256(tasks),
            "call_count": len(records),
            "valid_output_count": sum(record.structurally_valid for record in records),
            "invalid_output_count": sum(not record.structurally_valid for record in records),
            "input_tokens": sum(record.input_tokens for record in records),
            "output_tokens": sum(record.output_tokens for record in records),
            "billed_cost": billed_cost,
        },
    )
    print(f"Wrote {len(records)} raw judge records; billed cost ${billed_cost}")


def _execute_pilot(arguments: List[str]) -> None:
    """Execute or resume the approved five-percent prompt-development pilot."""
    _execute(arguments, JudgeStage.PILOT)


def _execute_full(arguments: List[str]) -> None:
    """Execute or resume all three frozen judges over every evaluated response."""
    _execute(arguments, JudgeStage.FULL)


def _freeze_contract(arguments: List[str]) -> None:
    """Freeze all three contracts after explicit review of a complete pilot."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring freeze-contract")
    _add_experiment_argument(parser)
    parser.add_argument("--pilot-sample", type=Path)
    parser.add_argument("--pilot-plan", type=Path)
    parser.add_argument("--pilot-results", type=Path)
    parser.add_argument("--pilot-adjudicated", type=Path)
    parser.add_argument("--protocol-manifest", type=Path, default=PROTOCOL_MANIFEST)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--confirm-pilot-reviewed", action="store_true", required=True)
    args = parser.parse_args(arguments)
    paths = _ensure_layout(args.experiment)
    pilot_sample = args.pilot_sample or paths["pilot_sample"]
    pilot_plan = args.pilot_plan or paths["pilot_plan"]
    pilot_results = args.pilot_results or paths["pilot_raw_results"]
    pilot_adjudicated = args.pilot_adjudicated or paths["pilot_final_judgments"]
    output = args.output or paths["frozen_contract"]
    sample = JudgePilotSample.model_validate(read_json(pilot_sample))
    tasks = [JudgeTask.model_validate(record) for record in read_jsonl(pilot_plan)]
    records = [JudgeCallRecord.model_validate(record) for record in read_jsonl(pilot_results)]
    adjudicated = [AdjudicatedJudgment.model_validate(record) for record in read_jsonl(pilot_adjudicated)]
    manifest = ProtocolManifest.model_validate(read_json(args.protocol_manifest))
    controls = manifest.generation_controls[manifest.scorer_model.model_slug]
    contract = freeze_judge_contract(sample, tasks, records, adjudicated, manifest.scorer_model, controls)
    write_json(output, contract)
    print(f"Frozen three-judge contract {contract.frozen_contract_sha256}")


def _apply_overrides(arguments: List[str]) -> None:
    """Apply the manual correction ledger and write typed adjudicated labels."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring apply-overrides")
    _add_experiment_argument(parser)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--raw-results", type=Path)
    parser.add_argument("--overrides", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(arguments)
    paths = _ensure_layout(args.experiment)
    plan = args.plan or paths["judge_plan"]
    raw_results = args.raw_results or paths["raw_results"]
    overrides_path = args.overrides or paths["manual_overrides"]
    output = args.output or paths["final_judgments"]
    tasks = [JudgeTask.model_validate(record) for record in read_jsonl(plan)]
    records = [JudgeCallRecord.model_validate(record) for record in read_jsonl(raw_results)]
    if not overrides_path.exists():
        write_jsonl(overrides_path, [])
    overrides = [JudgeOverride.model_validate(record) for record in read_jsonl(overrides_path)]
    runs = _experiment_runs(args.experiment)
    response_text_by_run = {run.run_unit_id: response_text_for_scoring(run) for run in runs}
    judgments = adjudicate_judgments(tasks, records, overrides, response_text_by_run)
    write_jsonl(output, judgments)
    print(f"Wrote {len(judgments)} adjudicated judgments using {len(overrides)} manual corrections")


def _calculate_outcomes(arguments: List[str]) -> None:
    """Join adjudicated labels to completed runs and write separate response outcomes."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring calculate-outcomes")
    _add_experiment_argument(parser)
    parser.add_argument("--runs", type=Path)
    parser.add_argument("--adjudicated", type=Path)
    parser.add_argument("--selections", type=Path)
    parser.add_argument("--scenarios", type=Path, default=SCENARIO_ROOT / "accepted_scenarios.jsonl")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args(arguments)
    paths = _ensure_layout(args.experiment)
    runs = [RunUnit.model_validate(record) for record in read_jsonl(args.runs)] if args.runs is not None else _experiment_runs(args.experiment)
    adjudicated = args.adjudicated or paths["final_judgments"]
    selections = args.selections
    if selections is None and paths["selections"].exists():
        selections = paths["selections"]
    output = args.output or paths["response_scores"]
    manifest_output = args.manifest or paths["manifest"]
    judgments = [AdjudicatedJudgment.model_validate(record) for record in read_jsonl(adjudicated)]
    run_ids = {run.run_unit_id for run in runs}
    recoveries = []
    if selections is not None:
        recoveries = [
            recovery
            for recovery in (SelectionRecoveryRecord.model_validate(record) for record in read_jsonl(selections))
            if recovery.run_unit_id in run_ids
        ]
    outcomes = score_responses(runs, _scenarios(args.scenarios), judgments, recoveries)
    write_jsonl(output, outcomes)
    tasks = [JudgeTask.model_validate(record) for record in read_jsonl(paths["judge_plan"])]
    raw_records = [JudgeCallRecord.model_validate(record) for record in read_jsonl(paths["raw_results"])]
    overrides = [JudgeOverride.model_validate(record) for record in read_jsonl(paths["manual_overrides"])]
    contract = FrozenJudgeContract.model_validate(read_json(paths["frozen_contract"]))
    scoring_manifest = ExperimentScoringManifest(
        experiment=ExperimentKind(args.experiment),
        judge_model_slug=contract.judge_model.model_slug,
        frozen_contract_sha256=contract.frozen_contract_sha256,
        source_response_count=len(runs),
        judge_call_count=len(raw_records),
        manual_override_count=len(overrides),
        final_judgment_count=len(judgments),
        selection_count=len(recoveries),
        response_score_count=len(outcomes),
        source_responses_sha256=artifact_sha256(runs),
        judge_plan_sha256=judge_plan_sha256(tasks),
        raw_judge_results_sha256=artifact_sha256(raw_records),
        final_judgments_sha256=artifact_sha256(judgments),
        response_scores_sha256=artifact_sha256(outcomes),
        generated_at=utc_now(),
    )
    write_json(manifest_output, scoring_manifest)
    print(f"Wrote {len(outcomes)} final response scores to {output}")


def main(command: str, arguments: List[str]) -> None:
    """Dispatch one scoring subcommand."""
    handlers = {
        "sample-pilot": _sample_pilot,
        "show-prompts": _show_prompts,
        "recover-selections": _recover_selections,
        "build-plan": _build_plan,
        "estimate-cost": _estimate_cost,
        "approve-execution": _approve_execution,
        "execute-pilot": _execute_pilot,
        "merge-results": _merge_results,
        "freeze-contract": _freeze_contract,
        "execute-full": _execute_full,
        "apply-overrides": _apply_overrides,
        "calculate-outcomes": _calculate_outcomes,
    }
    handlers[command](arguments)
