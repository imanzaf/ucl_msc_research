"""Evaluated-run usage aggregation and bounded batch execution."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from decimal import Decimal
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from src.common import utc_now
from src.experiments.planner import ExecutionBundle
from src.experiments.runner import cached_run, execute_assignment, write_run_cache
from src.llm.openrouter import OpenRouterClient
from src.models.experiments import BatchExecutionSummary, RunUnit, UsageTotals
from src.models.manifests import CostApproval, ProtocolManifest
from src.storage import read_json, write_json, write_jsonl


def _usage_totals(runs: Iterable[RunUnit]) -> UsageTotals:
    """Aggregate usage while reporting unavailable provider fields explicitly."""
    records = list(runs)
    responses = [run.response for run in records if run.response is not None]
    return UsageTotals(
        response_count=len(responses),
        input_tokens=sum(response.input_tokens or 0 for response in responses),
        output_tokens=sum(response.output_tokens or 0 for response in responses),
        billed_cost=sum((response.billed_cost or Decimal("0") for response in responses), Decimal("0")),
        missing_token_records=sum(response.input_tokens is None or response.output_tokens is None for response in responses),
        missing_cost_records=sum(response.billed_cost is None for response in responses),
    )


def summarize_runs(
    runs: Iterable[RunUnit],
    manifest: ProtocolManifest,
    approval: CostApproval,
    expected_response_count: int,
) -> BatchExecutionSummary:
    """Build model-level, experiment-level, and complete evaluated usage summaries."""
    records = list(runs)
    identifiers = [run.run_unit_id for run in records]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("run summaries require unique run-unit identifiers")
    by_model: Dict[str, UsageTotals] = {}
    for model_slug in sorted({run.model.model_slug for run in records}):
        by_model[model_slug] = _usage_totals(run for run in records if run.model.model_slug == model_slug)
    by_experiment: Dict[str, UsageTotals] = {}
    for experiment in sorted({run.experiment.value for run in records}):
        by_experiment[experiment] = _usage_totals(run for run in records if run.experiment.value == experiment)
    completed = len(records)
    return BatchExecutionSummary(
        protocol_manifest_sha256=manifest.manifest_sha256,
        approval_sha256=approval.approval_sha256,
        expected_response_count=expected_response_count,
        completed_response_count=completed,
        remaining_response_count=max(expected_response_count - completed, 0),
        totals=_usage_totals(records),
        by_model=by_model,
        by_experiment=by_experiment,
        generated_at=utc_now(),
    )


def load_run_caches(cache_directories: Iterable[Path]) -> List[RunUnit]:
    """Load every immutable evaluated response cache beneath declared directories."""
    runs: List[RunUnit] = []
    for directory in cache_directories:
        if not directory.exists():
            continue
        runs.extend(RunUnit.model_validate(read_json(path)) for path in sorted(directory.glob("*.json")))
    identifiers = [run.run_unit_id for run in runs]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("evaluated response caches contain duplicate run-unit identifiers")
    return runs


def execute_bundle_batch(
    bundles: List[ExecutionBundle],
    cache_directory: Path,
    client_factory: Callable[[], OpenRouterClient],
    approval: CostApproval,
    prior_billed_cost: Decimal,
    reserved_cost_per_call: Decimal,
    max_workers: int,
    progress: Optional[Callable[[int, int, RunUnit], None]] = None,
) -> List[RunUnit]:
    """Run an immutable bundle batch concurrently with resumable caches and a bounded in-flight reserve."""
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    if reserved_cost_per_call <= 0:
        raise ValueError("reserved cost per call must be positive")
    cache_directory.mkdir(parents=True, exist_ok=True)
    completed: Dict[str, RunUnit] = {}
    pending: List[ExecutionBundle] = []
    for bundle in bundles:
        existing = cached_run(cache_directory / f"{bundle.assignment.assignment_id}.json", bundle.assignment.assignment_id)
        if existing is None:
            pending.append(bundle)
        else:
            completed[existing.run_unit_id] = existing
    billed = prior_billed_cost + _usage_totals(completed.values()).billed_cost
    if billed > approval.approved_max_cost:
        raise PermissionError("existing billed cost exceeds the approved execution ceiling")

    def execute(bundle: ExecutionBundle) -> RunUnit:
        """Execute one bundle with a worker-owned provider client."""
        return execute_assignment(
            bundle.assignment,
            bundle.prompt,
            bundle.model,
            bundle.generation_controls,
            bundle.valid_fact_ids,
            client_factory(),
        )

    iterator = iter(pending)
    futures: Dict[Future[RunUnit], ExecutionBundle] = {}
    first_error: Optional[Exception] = None
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while True:
            while (
                first_error is None
                and len(futures) < max_workers
                and billed + reserved_cost_per_call * (len(futures) + 1) <= approval.approved_max_cost
            ):
                try:
                    bundle = next(iterator)
                except StopIteration:
                    break
                futures[executor.submit(execute, bundle)] = bundle
            if not futures:
                if first_error is not None:
                    raise first_error
                try:
                    next(iterator)
                except StopIteration:
                    break
                raise PermissionError("approved cost remaining is below the per-call safety reserve")
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                bundle = futures.pop(future)
                try:
                    run = future.result()
                except Exception as error:
                    first_error = first_error or error
                    continue
                write_run_cache(cache_directory / f"{bundle.assignment.assignment_id}.json", run)
                if run.response is None or run.response.billed_cost is None:
                    first_error = first_error or RuntimeError("provider omitted billed cost; response was preserved and batch execution stopped")
                    continue
                if run.response.billed_cost > reserved_cost_per_call:
                    first_error = first_error or RuntimeError(
                        "one provider charge exceeded the declared per-call reserve; response was preserved and batch execution stopped"
                    )
                billed += run.response.billed_cost
                if billed > approval.approved_max_cost:
                    first_error = first_error or PermissionError(
                        "completed provider charges exceed the approved execution ceiling; batch execution stopped"
                    )
                completed[run.run_unit_id] = run
                if progress is not None:
                    progress(len(completed), len(bundles), run)
    return [completed[bundle.assignment.assignment_id] for bundle in bundles]


def write_batch_results(path: Path, runs: List[RunUnit]) -> None:
    """Write one ordered JSONL result artifact after a batch is complete or resumed."""
    write_jsonl(path, runs)


def write_batch_summary(path: Path, summary: BatchExecutionSummary) -> None:
    """Write one stable evaluated usage and cost summary."""
    write_json(path, summary)
