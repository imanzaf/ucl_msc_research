"""Three-judge prompt development, execution, freezing, and adjudication commands."""

from __future__ import annotations

import argparse
import threading
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import List

from srcv2.experiments.accounting import load_run_caches
from srcv2.llm.openrouter import OpenRouterClient
from srcv2.models.catalog import load_model_catalog
from srcv2.models.enums import JudgeContract, JudgeStage
from srcv2.models.manifests import ProtocolManifest
from srcv2.models.queries import QueryVariant
from srcv2.models.scenarios import AcceptedScenario
from srcv2.models.scoring import (
    AdjudicatedJudgment,
    FrozenJudgeContract,
    JudgeCallRecord,
    JudgeExecutionApproval,
    JudgeExecutionEstimate,
    JudgeOverride,
    JudgePilotSample,
    JudgeTask,
    SelectionRecoveryRecord,
)
from srcv2.paths import EXPERIMENT_ROOT, SCENARIO_ROOT, experiment_paths
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
from srcv2.scoring.judges import build_judge_plan, judge_controls, judge_prompt_summary
from srcv2.scoring.pilot import build_pilot_sample, build_sampling_frame
from srcv2.scoring.selections import recover_selection_records
from srcv2.settings import CredentialRole, get_api_settings, get_model_settings
from srcv2.storage import read_json, read_jsonl, write_json, write_jsonl

JUDGE_ROOT = EXPERIMENT_ROOT / "response_judging_v7"
PROTOCOL_MANIFEST = EXPERIMENT_ROOT / "final_protocol_manifest.json"


def _ensure_layout() -> None:
    """Create the standard output layout for the scoring workflow."""
    for name in ("results", "cache", "logs", "assets", "checkpoints"):
        (JUDGE_ROOT / name).mkdir(parents=True, exist_ok=True)


def _frozen_runs() -> list:
    """Load the six active evaluated-response caches in protocol order."""
    names = (
        "user_state_adaptation_v2",
        "information_budget_v1",
        "word_budget_external_validity_v1",
        "single_fact_priority_v1",
        "ownership_role_control_v1",
        "option_first_v1",
    )
    return load_run_caches(experiment_paths(name)["cache"] for name in names)


def _scenarios(path: Path) -> List[AcceptedScenario]:
    """Load the accepted six-fact scenario corpus."""
    return [AcceptedScenario.model_validate(record) for record in read_jsonl(path)]


def _queries(path: Path) -> List[QueryVariant]:
    """Load the accepted customer-query variants."""
    return [QueryVariant.model_validate(record) for record in read_jsonl(path)]


def _sample_pilot(arguments: List[str]) -> None:
    """Draw and freeze the stratified 191-response judge-development sample."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring sample-pilot")
    parser.add_argument("--seed", type=int, default=410191)
    parser.add_argument("--output", type=Path, default=JUDGE_ROOT / "checkpoints" / "pilot_sample.json")
    args = parser.parse_args(arguments)
    sample = build_pilot_sample(build_sampling_frame(_frozen_runs()), random_seed=args.seed)
    write_json(args.output, sample)
    print(f"Wrote {len(sample.response_ids)} judge-development response identifiers to {args.output}")


def _show_prompts(arguments: List[str]) -> None:
    """Write the three exact prompts, schemas, hashes, and output ceilings for review."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring show-prompts")
    parser.add_argument("--output", type=Path, default=JUDGE_ROOT / "judge_prompts.json")
    args = parser.parse_args(arguments)
    _ensure_layout()
    write_json(
        args.output,
        {
            "schema_version": "4.0.0",
            "judge_model_slug": load_model_catalog().scoring_model.model_slug,
            "judges": judge_prompt_summary(),
        },
    )
    print(f"Wrote three reviewable judge contracts to {args.output}")


def _recover_selections(arguments: List[str]) -> None:
    """Recover unambiguous exact-budget selections without changing response adherence."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring recover-selections")
    parser.add_argument("--scenarios", type=Path, default=SCENARIO_ROOT / "accepted_scenarios.jsonl")
    parser.add_argument("--output", type=Path, default=JUDGE_ROOT / "results" / "exact_budget_selections.jsonl")
    parser.add_argument("--summary", type=Path, default=JUDGE_ROOT / "logs" / "exact_budget_selection_summary.json")
    args = parser.parse_args(arguments)
    runs = [run for run in _frozen_runs() if run.experiment.value == "information_budget_v1"]
    run_by_id = {run.run_unit_id: run for run in runs}
    records: List[SelectionRecoveryRecord] = recover_selection_records(runs, _scenarios(args.scenarios))
    if len(records) != 1050:
        raise ValueError("selection recovery requires all 1,050 information-budget responses")
    write_jsonl(args.output, records)
    counts = Counter(record.source for record in records)
    by_model = {
        model_slug: dict(Counter(record.source for record in records if run_by_id[record.run_unit_id].model.model_slug == model_slug))
        for model_slug in sorted({run.model.model_slug for run in runs})
    }
    write_json(
        args.summary,
        {
            "schema_version": "4.0.0",
            "response_count": len(records),
            "usable_selection_count": sum(record.selection_usable for record in records),
            "format_adherent_count": sum(record.format_adherent for record in records),
            "by_source": dict(counts),
            "by_model": by_model,
        },
    )
    print(f"Wrote {len(records)} selection records: " + ", ".join(f"{source}={count}" for source, count in sorted(counts.items())))


def _build_plan(arguments: List[str]) -> None:
    """Build a complete or one-contract judge plan for the pilot or frozen corpus."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring build-plan")
    parser.add_argument("--stage", choices=[stage.value for stage in JudgeStage], required=True)
    parser.add_argument("--contract", choices=[contract.value for contract in JudgeContract])
    parser.add_argument("--pilot-sample", type=Path, default=JUDGE_ROOT / "checkpoints" / "pilot_sample.json")
    parser.add_argument("--scenarios", type=Path, default=SCENARIO_ROOT / "accepted_scenarios.jsonl")
    parser.add_argument("--queries", type=Path, default=SCENARIO_ROOT / "query_variants.jsonl")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(arguments)
    stage = JudgeStage(args.stage)
    response_ids = None
    if stage == JudgeStage.PILOT:
        response_ids = JudgePilotSample.model_validate(read_json(args.pilot_sample)).response_ids
    tasks = build_judge_plan(_frozen_runs(), _scenarios(args.scenarios), _queries(args.queries), stage, response_ids)
    response_count = 191 if stage == JudgeStage.PILOT else 3822
    if args.contract is not None:
        contract = JudgeContract(args.contract)
        tasks = [task for task in tasks if task.contract == contract]
        calls_per_response = 6 if contract == JudgeContract.CONTENT else 1
    else:
        calls_per_response = 8
    expected = response_count * calls_per_response
    if len(tasks) != expected:
        raise ValueError(f"{stage.value} judge plan requires exactly {expected} calls")
    write_jsonl(args.output, tasks)
    print(f"Wrote {len(tasks)} judge calls with plan hash {judge_plan_sha256(tasks)}")


def _merge_results(arguments: List[str]) -> None:
    """Merge reusable and replacement raw records into one ordered plan result."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring merge-results")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(arguments)
    tasks = [JudgeTask.model_validate(record) for record in read_jsonl(args.plan)]
    record_sets = [[JudgeCallRecord.model_validate(record) for record in read_jsonl(path)] for path in args.source]
    records = merge_judge_records(tasks, record_sets)
    write_jsonl(args.output, records)
    print(f"Wrote {len(records)} ordered raw judge records from {len(record_sets)} sources")


def _estimate_cost(arguments: List[str]) -> None:
    """Estimate the exact judge plan using caller-supplied current token prices."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring estimate-cost")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--protocol-manifest", type=Path, default=PROTOCOL_MANIFEST)
    parser.add_argument("--input-price-per-million", type=Decimal, required=True)
    parser.add_argument("--output-price-per-million", type=Decimal, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(arguments)
    tasks = [JudgeTask.model_validate(record) for record in read_jsonl(args.plan)]
    manifest = ProtocolManifest.model_validate(read_json(args.protocol_manifest))
    controls = manifest.generation_controls[manifest.scorer_model.model_slug]
    estimate = build_execution_estimate(tasks, controls, args.input_price_per_million, args.output_price_per_million)
    write_json(args.output, estimate)
    print(estimate.model_dump_json(indent=2))


def _approve_execution(arguments: List[str]) -> None:
    """Record bounded authorization for one exact pilot or full judge plan."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring approve-execution")
    parser.add_argument("--estimate", type=Path, required=True)
    parser.add_argument("--approved-max-cost", type=Decimal, required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-paid-execution", action="store_true", required=True)
    args = parser.parse_args(arguments)
    estimate = JudgeExecutionEstimate.model_validate(read_json(args.estimate))
    approval = build_execution_approval(estimate, args.approved_max_cost, args.approved_by, args.note)
    write_json(args.output, approval)
    print(f"Wrote judge execution approval {approval.approval_sha256}")


def _execute(arguments: List[str], stage: JudgeStage) -> None:
    """Execute or resume one approved pilot or frozen full judge plan."""
    parser = argparse.ArgumentParser(prog=f"risk-comm-v2 scoring execute-{stage.value}")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--protocol-manifest", type=Path, default=PROTOCOL_MANIFEST)
    parser.add_argument("--estimate", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--frozen-contract", type=Path)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--max-workers", type=int, default=8)
    args = parser.parse_args(arguments)
    tasks = [JudgeTask.model_validate(record) for record in read_jsonl(args.plan)]
    if not tasks or any(task.stage != stage for task in tasks):
        raise ValueError(f"execute-{stage.value} requires a {stage.value}-only judge plan")
    manifest = ProtocolManifest.model_validate(read_json(args.protocol_manifest))
    base_controls = manifest.generation_controls[manifest.scorer_model.model_slug]
    if stage == JudgeStage.FULL:
        if args.frozen_contract is None:
            raise ValueError("full judge execution requires --frozen-contract")
        contract = FrozenJudgeContract.model_validate(read_json(args.frozen_contract))
        validate_full_plan(tasks, contract)
        if contract.judge_model != manifest.scorer_model:
            raise PermissionError("frozen contract and protocol manifest use different judge models")
        expected_controls = {judge: contract.generation_controls[judge] for judge in contract.generation_controls}
        if expected_controls != {judge: judge_controls(base_controls, judge) for judge in expected_controls}:
            raise PermissionError("current judge controls differ from the frozen contract")
    estimate = JudgeExecutionEstimate.model_validate(read_json(args.estimate))
    approval = JudgeExecutionApproval.model_validate(read_json(args.approval))
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
        args.cache_dir,
        max_workers=args.max_workers,
        progress=report,
    )
    write_jsonl(args.output, records)
    billed_cost = sum((record.billed_cost or Decimal(0) for record in records), Decimal(0))
    write_json(
        args.summary,
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
    """Execute or resume the approved 191-response prompt-development pilot."""
    _execute(arguments, JudgeStage.PILOT)


def _execute_full(arguments: List[str]) -> None:
    """Execute or resume all three frozen judges over every evaluated response."""
    _execute(arguments, JudgeStage.FULL)


def _freeze_contract(arguments: List[str]) -> None:
    """Freeze all three contracts after explicit review of a complete pilot."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring freeze-contract")
    parser.add_argument("--pilot-sample", type=Path, required=True)
    parser.add_argument("--pilot-plan", type=Path, required=True)
    parser.add_argument("--pilot-results", type=Path, required=True)
    parser.add_argument("--pilot-adjudicated", type=Path, required=True)
    parser.add_argument("--protocol-manifest", type=Path, default=PROTOCOL_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-pilot-reviewed", action="store_true", required=True)
    args = parser.parse_args(arguments)
    sample = JudgePilotSample.model_validate(read_json(args.pilot_sample))
    tasks = [JudgeTask.model_validate(record) for record in read_jsonl(args.pilot_plan)]
    records = [JudgeCallRecord.model_validate(record) for record in read_jsonl(args.pilot_results)]
    adjudicated = [AdjudicatedJudgment.model_validate(record) for record in read_jsonl(args.pilot_adjudicated)]
    manifest = ProtocolManifest.model_validate(read_json(args.protocol_manifest))
    controls = manifest.generation_controls[manifest.scorer_model.model_slug]
    contract = freeze_judge_contract(sample, tasks, records, adjudicated, manifest.scorer_model, controls)
    write_json(args.output, contract)
    print(f"Frozen three-judge contract {contract.frozen_contract_sha256}")


def _apply_overrides(arguments: List[str]) -> None:
    """Apply the manual correction ledger and write typed adjudicated labels."""
    parser = argparse.ArgumentParser(prog="risk-comm-v2 scoring apply-overrides")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--raw-results", type=Path, required=True)
    parser.add_argument("--overrides", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(arguments)
    tasks = [JudgeTask.model_validate(record) for record in read_jsonl(args.plan)]
    records = [JudgeCallRecord.model_validate(record) for record in read_jsonl(args.raw_results)]
    overrides = [JudgeOverride.model_validate(record) for record in read_jsonl(args.overrides)]
    judgments = adjudicate_judgments(tasks, records, overrides)
    write_jsonl(args.output, judgments)
    print(f"Wrote {len(judgments)} adjudicated judgments using {len(overrides)} manual corrections")


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
    }
    handlers[command](arguments)
