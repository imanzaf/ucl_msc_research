"""Experiment planning, freezing, costing, execution, and asset commands."""

from __future__ import annotations

import argparse
import threading
from decimal import Decimal
from pathlib import Path
from typing import List

from src.common import artifact_sha256, utc_now
from src.experiments.accounting import execute_bundle_batch, load_run_caches, summarize_runs, write_batch_results, write_batch_summary
from src.experiments.matrix import build_matrix, response_counts
from src.experiments.planner import CostEstimate, ExecutionBundle, build_cost_estimate, build_execution_bundles, require_cost_approval
from src.experiments.runner import execute_assignment, write_run_cache
from src.llm.openrouter import OpenRouterClient
from src.models.catalog import load_model_catalog
from src.models.experiments import ProviderSnapshot
from src.models.manifests import CostApproval, PreflightApproval, ProtocolManifest
from src.models.queries import QueryVariant
from src.models.scenarios import AcceptedScenario
from src.models.seeds import ScenarioSeedSet
from src.paths import EXPERIMENT_ROOT, SCENARIO_ROOT, experiment_paths
from src.protocol import PreflightResult, freeze_protocol_manifest
from src.scenarios.prompt_protocol import PromptProtocolApproval
from src.scenarios.queries import QueryProtocolApproval
from src.settings import CredentialRole, get_api_settings, get_model_settings
from src.storage import read_json, read_jsonl, write_json, write_jsonl


def _build_plan(arguments: List[str]) -> None:
    """Build and persist all active matrix assignments by experiment."""
    parser = argparse.ArgumentParser(prog="risk-comm experiment build-plan")
    parser.add_argument("--seed-set", type=Path, default=SCENARIO_ROOT / "final_scenario_generation_seeds.json")
    args = parser.parse_args(arguments)
    seed_set = ScenarioSeedSet.model_validate(read_json(args.seed_set))
    catalog = load_model_catalog()
    assignments = build_matrix(seed_set, [model.model_slug for model in catalog.evaluated_models])
    for experiment_name, count in response_counts(assignments).items():
        selected = [assignment for assignment in assignments if assignment.cell.kind.value == experiment_name]
        paths = experiment_paths(experiment_name)
        for name, path in paths.items():
            if name != "config":
                path.mkdir(parents=True, exist_ok=True)
        run_plan_path = paths["root"] / "run_plan.jsonl"
        write_jsonl(run_plan_path, selected)
        plan_hash = artifact_sha256([assignment.model_dump(mode="json") for assignment in selected])
        write_json(
            paths["config"],
            {
                "schema_version": "4.0.0",
                "experiment": experiment_name,
                "execution_status": selected[0].execution_status.value,
                "response_count": count,
                "run_plan": str(run_plan_path),
                "run_plan_sha256": plan_hash,
            },
        )
    print(f"Built {len(assignments)} assignments")


def _freeze_protocol(arguments: List[str]) -> None:
    """Freeze a model/provider panel from separately authorized preflight results."""
    parser = argparse.ArgumentParser(prog="risk-comm experiment freeze-protocol")
    parser.add_argument("--preflight-results", type=Path, required=True)
    parser.add_argument("--scenarios", type=Path, default=SCENARIO_ROOT / "accepted_scenarios.jsonl")
    parser.add_argument("--queries", type=Path, default=SCENARIO_ROOT / "query_variants.jsonl")
    parser.add_argument("--query-approval", type=Path, default=SCENARIO_ROOT / "manual_revisions" / "query_protocol_approval.json")
    parser.add_argument("--prompt-approval", type=Path, default=SCENARIO_ROOT / "manual_revisions" / "prompt_protocol_approval.json")
    parser.add_argument("--output", type=Path, default=EXPERIMENT_ROOT / "final_protocol_manifest.json")
    args = parser.parse_args(arguments)
    results = [PreflightResult.model_validate(record) for record in read_jsonl(args.preflight_results)]
    scenario_records = read_jsonl(args.scenarios)
    scenarios = [AcceptedScenario.model_validate(record) for record in scenario_records]
    queries = [QueryVariant.model_validate(record) for record in read_jsonl(args.queries)]
    query_approval = QueryProtocolApproval.model_validate(read_json(args.query_approval))
    if artifact_sha256(queries) != query_approval.query_variants_sha256:
        raise PermissionError("query variants differ from the researcher-approved query protocol")
    prompt_approval = PromptProtocolApproval.model_validate(read_json(args.prompt_approval))
    if artifact_sha256(scenario_records) != prompt_approval.source_scenarios_sha256:
        raise PermissionError("accepted scenarios differ from the researcher-approved prompt protocol")
    corpus_hash = artifact_sha256({"scenarios": scenarios, "queries": queries})
    manifest = freeze_protocol_manifest(load_model_catalog(), results, corpus_hash, args.output)
    print(f"Frozen protocol manifest {manifest.manifest_sha256}")


def _approve_preflight(arguments: List[str]) -> None:
    """Create a hash-bound approval only from an explicit CLI confirmation."""
    parser = argparse.ArgumentParser(prog="risk-comm experiment approve-preflight")
    parser.add_argument("--estimated-max-cost", type=Decimal, required=True)
    parser.add_argument("--approved-max-cost", type=Decimal, required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-paid-preflight", action="store_true", required=True)
    args = parser.parse_args(arguments)
    approved_at = utc_now()
    base = {
        "schema_version": "4.0.0",
        "model_catalog_sha256": artifact_sha256(load_model_catalog()),
        "estimated_max_cost": args.estimated_max_cost,
        "approved_max_cost": args.approved_max_cost,
        "currency": "USD",
        "approved_by": args.approved_by,
        "approved_at": approved_at,
        "approval_note": args.note,
    }
    approval = PreflightApproval(**base, approval_sha256=artifact_sha256(base))
    write_json(args.output, approval)
    print(f"Wrote preflight approval {approval.approval_sha256} to {args.output}")


def _preflight(arguments: List[str]) -> None:
    """Run explicitly approved compatibility probes under the declared routing policy."""
    parser = argparse.ArgumentParser(prog="risk-comm experiment preflight")
    parser.add_argument("--candidate-routes", type=Path, help="Optional model-to-route overrides; omit for catalog routing")
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(arguments)
    catalog = load_model_catalog()
    catalog_hash = artifact_sha256(catalog)
    approval = PreflightApproval.model_validate(read_json(args.approval))
    if approval.model_catalog_sha256 != catalog_hash:
        raise PermissionError("preflight approval belongs to a different model catalog")
    routes = read_json(args.candidate_routes) if args.candidate_routes else {}
    agent_client = OpenRouterClient.from_settings(get_api_settings(), get_model_settings(), CredentialRole.EVALUATED_MODEL)
    scoring_client = OpenRouterClient.from_settings(get_api_settings(), get_model_settings(), CredentialRole.SCORING)
    results: List[PreflightResult] = []
    entries = [*catalog.evaluated_models, catalog.scoring_model]
    for entry in entries:
        route = routes.get(
            entry.model_slug,
            {"provider_name": entry.provider_name, "provider_endpoint": entry.provider_endpoint},
        )
        if not isinstance(route, dict) or not route.get("provider_name") or not route.get("provider_endpoint"):
            raise ValueError(f"invalid provider route for {entry.model_slug}")
        metadata = {**entry.model_dump(mode="json"), **route}
        snapshot = ProviderSnapshot(
            model_slug=entry.model_slug,
            model_access=entry.model_access,
            licence_category=entry.licence_category,
            total_parameters=entry.total_parameters,
            active_parameters=entry.active_parameters,
            provider_name=str(route["provider_name"]),
            provider_endpoint=str(route["provider_endpoint"]),
            routing_policy=entry.routing_policy,
            metadata_snapshot_sha256=artifact_sha256(metadata),
            preflight_passed=True,
        )
        client = scoring_client if entry.model_slug == catalog.scoring_model.model_slug else agent_client
        reply = client.complete(
            snapshot,
            entry.generation_controls,
            [{"role": "user", "content": "Compatibility check: reply with exactly PREFLIGHT_OK."}],
        )
        accepted_controls = ["max_output_tokens"]
        accepted_controls.extend(
            name
            for name, value in (
                ("temperature", entry.generation_controls.temperature),
                ("seed", entry.generation_controls.seed),
                ("reasoning_effort", entry.generation_controls.reasoning_effort),
            )
            if value is not None
        )
        accepted_controls.extend(sorted(entry.generation_controls.extra_parameters))
        results.append(
            PreflightResult(
                model_slug=entry.model_slug,
                returned_model_version=reply.returned_model_version,
                provider_name=reply.provider_name or snapshot.provider_name,
                provider_endpoint=snapshot.provider_endpoint,
                accepted_controls=accepted_controls,
                rejected_controls=[],
                semantic_response_received=bool(reply.text.strip()),
                completed_at=utc_now(),
                provider_request_id=reply.provider_request_id,
            )
        )
    write_jsonl(args.output, results)
    print(f"Wrote {len(results)} successful compatibility probes to {args.output}")


def _estimate_cost(arguments: List[str]) -> None:
    """Record a caller-supplied current-pricing cost estimate without making API calls."""
    parser = argparse.ArgumentParser(prog="risk-comm experiment estimate-cost")
    parser.add_argument("--protocol-manifest", type=Path, required=True)
    parser.add_argument("--model-costs", type=Path, required=True, help="JSON object mapping model slugs to maximum USD costs")
    parser.add_argument("--input-tokens", type=int, required=True)
    parser.add_argument("--output-token-ceiling", type=int, required=True)
    parser.add_argument("--output", type=Path, default=EXPERIMENT_ROOT / "cost_estimate.json")
    args = parser.parse_args(arguments)
    manifest = ProtocolManifest.model_validate(read_json(args.protocol_manifest))
    costs = {name: Decimal(str(value)) for name, value in read_json(args.model_costs).items()}
    estimate = build_cost_estimate(manifest.manifest_sha256, args.input_tokens, args.output_token_ceiling, costs)
    write_json(args.output, estimate)
    print(estimate.model_dump_json(indent=2))


def _build_bundles(arguments: List[str]) -> None:
    """Materialize one experiment run plan from accepted scenarios and a frozen manifest."""
    parser = argparse.ArgumentParser(prog="risk-comm experiment build-bundles")
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--queries", type=Path, default=SCENARIO_ROOT / "query_variants.jsonl")
    parser.add_argument("--protocol-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(arguments)
    from src.experiments.matrix import MatrixAssignment

    assignments = [MatrixAssignment.model_validate(record) for record in read_jsonl(args.run_plan)]
    scenarios = [AcceptedScenario.model_validate(record) for record in read_jsonl(args.scenarios)]
    queries = [QueryVariant.model_validate(record) for record in read_jsonl(args.queries)]
    manifest = ProtocolManifest.model_validate(read_json(args.protocol_manifest))
    bundles = build_execution_bundles(assignments, scenarios, queries, manifest)
    write_jsonl(args.output, bundles)
    print(f"Wrote {len(bundles)} immutable execution bundles to {args.output}")


def _approve_execution(arguments: List[str]) -> None:
    """Create an exact-manifest paid-execution approval after cost estimation."""
    parser = argparse.ArgumentParser(prog="risk-comm experiment approve-execution")
    parser.add_argument("--protocol-manifest", type=Path, required=True)
    parser.add_argument("--cost-estimate", type=Path, required=True)
    parser.add_argument("--approved-max-cost", type=Decimal, required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-paid-execution", action="store_true", required=True)
    args = parser.parse_args(arguments)
    manifest = ProtocolManifest.model_validate(read_json(args.protocol_manifest))
    estimate = read_json(args.cost_estimate)
    estimated_cost = Decimal(str(estimate["estimated_max_cost"]))
    approved_at = utc_now()
    base = {
        "schema_version": "4.0.0",
        "protocol_manifest_sha256": manifest.manifest_sha256,
        "estimated_max_cost": estimated_cost,
        "currency": "USD",
        "approved_max_cost": args.approved_max_cost,
        "approved_by": args.approved_by,
        "approved_at": approved_at,
        "approval_note": args.note,
    }
    approval = CostApproval(**base, approval_sha256=artifact_sha256(base))
    write_json(args.output, approval)
    print(f"Wrote execution approval {approval.approval_sha256} to {args.output}")


def _execute_unit(arguments: List[str]) -> None:
    """Execute one frozen unit only after exact-manifest cost approval."""
    parser = argparse.ArgumentParser(prog="risk-comm experiment execute-unit")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--protocol-manifest", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--estimated-cost", type=Decimal, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(arguments)
    manifest = ProtocolManifest.model_validate(read_json(args.protocol_manifest))
    require_cost_approval(args.approval, manifest.manifest_sha256, args.estimated_cost)
    bundle = ExecutionBundle.model_validate(read_json(args.bundle))
    if bundle.protocol_manifest_sha256 != manifest.manifest_sha256:
        raise PermissionError("execution bundle belongs to a different protocol manifest")
    expected_model = next((model for model in manifest.evaluated_models if model.model_slug == bundle.model.model_slug), None)
    if expected_model != bundle.model or manifest.generation_controls.get(bundle.model.model_slug) != bundle.generation_controls:
        raise PermissionError("execution bundle model or controls differ from the frozen protocol")
    client = OpenRouterClient.from_settings(get_api_settings(), get_model_settings(), CredentialRole.EVALUATED_MODEL)
    run = execute_assignment(
        bundle.assignment,
        bundle.prompt,
        bundle.model,
        bundle.generation_controls,
        bundle.valid_fact_ids,
        client,
    )
    write_run_cache(args.output, run)
    print(f"Wrote immutable run unit {run.run_unit_id} to {args.output}")


def _validate_frozen_bundle(bundle: ExecutionBundle, manifest: ProtocolManifest) -> None:
    """Reject a batch bundle that differs from the frozen model panel or controls."""
    if bundle.protocol_manifest_sha256 != manifest.manifest_sha256:
        raise PermissionError("execution bundle belongs to a different protocol manifest")
    expected_model = next((model for model in manifest.evaluated_models if model.model_slug == bundle.model.model_slug), None)
    if expected_model != bundle.model or manifest.generation_controls.get(bundle.model.model_slug) != bundle.generation_controls:
        raise PermissionError("execution bundle model or controls differ from the frozen protocol")


def _execute_batch(arguments: List[str]) -> None:
    """Execute or resume one complete experiment with immutable caches and bounded spend."""
    parser = argparse.ArgumentParser(prog="risk-comm experiment execute-batch")
    parser.add_argument("--bundles", type=Path, required=True)
    parser.add_argument("--protocol-manifest", type=Path, required=True)
    parser.add_argument("--cost-estimate", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--reserved-cost-per-call", type=Decimal, default=Decimal("0.10"))
    args = parser.parse_args(arguments)
    manifest = ProtocolManifest.model_validate(read_json(args.protocol_manifest))
    estimate = CostEstimate.model_validate(read_json(args.cost_estimate))
    if estimate.protocol_manifest_sha256 != manifest.manifest_sha256:
        raise PermissionError("cost estimate belongs to a different protocol manifest")
    approval = require_cost_approval(args.approval, manifest.manifest_sha256, estimate.estimated_max_cost)
    bundles = [ExecutionBundle.model_validate(record) for record in read_jsonl(args.bundles)]
    if not bundles:
        raise ValueError("execution batch contains no bundles")
    for bundle in bundles:
        _validate_frozen_bundle(bundle, manifest)
    experiments = {bundle.assignment.cell.kind for bundle in bundles}
    if len(experiments) != 1:
        raise ValueError("one batch must contain exactly one experiment")
    experiment = next(iter(experiments))
    paths = experiment_paths(experiment.value)
    for name in ("results", "cache", "logs", "checkpoints"):
        paths[name].mkdir(parents=True, exist_ok=True)
    other_cache_directories = [experiment_paths(kind.value)["cache"] for kind in manifest.experiments if kind != experiment]
    prior_runs = load_run_caches(other_cache_directories)
    prior_cost = summarize_runs(prior_runs, manifest, approval, len(prior_runs)).totals.billed_cost
    thread_local = threading.local()

    def client_factory() -> OpenRouterClient:
        """Return one evaluated-model client owned by the current worker thread."""
        client = getattr(thread_local, "client", None)
        if client is None:
            client = OpenRouterClient.from_settings(get_api_settings(), get_model_settings(), CredentialRole.EVALUATED_MODEL)
            thread_local.client = client
        return client

    def progress(completed: int, expected: int, run: object) -> None:
        """Emit durable, line-buffered progress without exposing response content."""
        if completed == expected or completed % 25 == 0:
            print(f"{experiment.value}: {completed}/{expected} responses cached", flush=True)

    runs = execute_bundle_batch(
        bundles,
        paths["cache"],
        client_factory,
        approval,
        prior_cost,
        args.reserved_cost_per_call,
        args.max_workers,
        progress,
    )
    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    result_path = paths["results"] / f"{timestamp}_results.jsonl"
    write_batch_results(result_path, runs)
    experiment_summary = summarize_runs(runs, manifest, approval, len(bundles))
    write_batch_summary(paths["checkpoints"] / "execution_summary.json", experiment_summary)
    all_cache_directories = [experiment_paths(kind.value)["cache"] for kind in manifest.experiments]
    all_runs = load_run_caches(all_cache_directories)
    global_summary = summarize_runs(all_runs, manifest, approval, sum(manifest.expected_response_counts.values()))
    write_batch_summary(EXPERIMENT_ROOT / "final_protocol_usage_summary.json", global_summary)
    print(
        f"Completed {len(runs)} {experiment.value} responses; "
        f"global billed cost is ${global_summary.totals.billed_cost} across {len(all_runs)} responses"
    )


def main(command: str, arguments: List[str]) -> None:
    """Dispatch one experiment subcommand."""
    handlers = {
        "build-plan": _build_plan,
        "approve-preflight": _approve_preflight,
        "preflight": _preflight,
        "freeze-protocol": _freeze_protocol,
        "estimate-cost": _estimate_cost,
        "build-bundles": _build_bundles,
        "approve-execution": _approve_execution,
        "execute-unit": _execute_unit,
        "execute-batch": _execute_batch,
    }
    handlers[command](arguments)
