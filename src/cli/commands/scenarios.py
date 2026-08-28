"""Scenario import, validation, generation-request, and query commands."""

from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
from typing import List

from src.common import artifact_sha256
from src.llm.openrouter import OpenRouterClient
from src.models.manifests import ScenarioGenerationApproval
from src.models.queries import AuthoredQueryFamily
from src.models.scenarios import AcceptedScenario
from src.models.seeds import ScenarioSeedSet
from src.paths import SCENARIO_ROOT, SCENARIO_SOURCE_ARCHIVE, scenario_generation_paths
from src.scenarios.curation import CorpusCurationApproval, assemble_curated_pending_corpus, build_curation_approval
from src.scenarios.execution import build_generation_approval, build_generation_estimate, run_scenario_generation
from src.scenarios.generation import GeneratedScenarioOutput, GenerationRequest, assemble_pending_corpus, build_generation_requests
from src.scenarios.import_package import import_package
from src.scenarios.prompt_protocol import (
    PromptContextSet,
    PromptProtocolApproval,
    apply_prompt_protocol,
    attach_prompt_contexts,
    build_prompt_protocol_approval,
)
from src.scenarios.queries import (
    QueryProtocolApproval,
    apply_query_protocol,
    build_query_protocol_approval,
    build_user_state_queries,
    validate_query_corpus,
)
from src.scenarios.validation import audit_seed_set
from src.settings import CredentialRole, get_api_settings, get_model_settings
from src.storage import read_json, read_jsonl, write_json, write_jsonl

DEFAULT_SOURCE = Path("/Users/iman/Downloads/scenario_generation_v4.0.0_package.zip")


def _load_seed_set(path: Path) -> ScenarioSeedSet:
    """Load and validate the corrected generation seed set."""
    return ScenarioSeedSet.model_validate(read_json(path))


def _import_package(arguments: List[str]) -> None:
    """Run the verified source-package import."""
    parser = argparse.ArgumentParser(prog="risk-comm scenarios import-package")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=SCENARIO_ROOT)
    parser.add_argument("--preserve-archive", type=Path, default=SCENARIO_SOURCE_ARCHIVE)
    args = parser.parse_args(arguments)
    seed_set = import_package(args.source, args.target, args.preserve_archive)
    print(f"Imported {sum(len(use_case.replications) for use_case in seed_set.use_cases)} scenarios to {args.target}")


def _validate(arguments: List[str]) -> None:
    """Validate and print corrected corpus arithmetic."""
    parser = argparse.ArgumentParser(prog="risk-comm scenarios validate")
    parser.add_argument("--seed-set", type=Path, default=SCENARIO_ROOT / "final_scenario_generation_seeds.json")
    parser.add_argument("--report", type=Path, default=SCENARIO_ROOT / "corpus_audit.json")
    args = parser.parse_args(arguments)
    audit = audit_seed_set(_load_seed_set(args.seed_set))
    write_json(args.report, audit)
    print(audit.model_dump_json(indent=2))
    if not audit.passed:
        raise SystemExit(1)


def _build_generation_requests(arguments: List[str]) -> None:
    """Write one immutable generation request for each scenario."""
    parser = argparse.ArgumentParser(prog="risk-comm scenarios build-generation-requests")
    parser.add_argument("--seed-set", type=Path, default=SCENARIO_ROOT / "scenario_generation_seeds.json")
    parser.add_argument("--output", type=Path, default=SCENARIO_ROOT / "generation_requests.jsonl")
    args = parser.parse_args(arguments)
    requests = build_generation_requests(_load_seed_set(args.seed_set))
    write_jsonl(args.output, requests)
    print(f"Wrote {len(requests)} one-shot generation requests to {args.output}")


def _load_generation_requests(path: Path) -> List[GenerationRequest]:
    """Load the exact hash-validated one-shot generation request batch."""
    return [GenerationRequest.model_validate(record) for record in read_jsonl(path)]


def _estimate_generation_cost(arguments: List[str]) -> None:
    """Persist the transparent GPT-5.4 list-price estimate without making API calls."""
    paths = scenario_generation_paths()
    parser = argparse.ArgumentParser(prog="risk-comm scenarios estimate-generation-cost")
    parser.add_argument("--requests", type=Path, default=SCENARIO_ROOT / "generation_requests.jsonl")
    parser.add_argument("--output", type=Path, default=paths["results"] / "cost_estimate.json")
    args = parser.parse_args(arguments)
    estimate = build_generation_estimate(_load_generation_requests(args.requests))
    write_json(args.output, estimate)
    print(estimate.model_dump_json(indent=2))


def _approve_generation(arguments: List[str]) -> None:
    """Record the researcher's explicit GPT-5.4 generation spending authorization."""
    paths = scenario_generation_paths()
    parser = argparse.ArgumentParser(prog="risk-comm scenarios approve-generation")
    parser.add_argument("--requests", type=Path, default=SCENARIO_ROOT / "generation_requests.jsonl")
    parser.add_argument("--approved-max-cost", type=Decimal, required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--output", type=Path, default=paths["approval"])
    parser.add_argument("--confirm-paid-generation", action="store_true", required=True)
    args = parser.parse_args(arguments)
    estimate = build_generation_estimate(_load_generation_requests(args.requests))
    approval = build_generation_approval(estimate, args.approved_max_cost, args.approved_by, args.note)
    write_json(args.output, approval)
    print(f"Wrote scenario-generation approval {approval.approval_sha256} to {args.output}")


def _run_generation(arguments: List[str]) -> None:
    """Run or resume every approved one-shot scenario-generation request."""
    paths = scenario_generation_paths()
    parser = argparse.ArgumentParser(prog="risk-comm scenarios run-generation")
    parser.add_argument("--requests", type=Path, default=SCENARIO_ROOT / "generation_requests.jsonl")
    parser.add_argument("--approval", type=Path, default=paths["approval"])
    parser.add_argument("--generated-outputs", type=Path, default=SCENARIO_ROOT / "generated_outputs.jsonl")
    args = parser.parse_args(arguments)
    approval = ScenarioGenerationApproval.model_validate(read_json(args.approval))
    client = OpenRouterClient.from_settings(get_api_settings(), get_model_settings(), CredentialRole.SCENARIO_GENERATION)
    summary = run_scenario_generation(_load_generation_requests(args.requests), approval, client, args.generated_outputs)
    print(summary.model_dump_json(indent=2))


def _build_queries(arguments: List[str]) -> None:
    """Write all approved scenario-specific affect-by-length query variants."""
    parser = argparse.ArgumentParser(prog="risk-comm scenarios build-queries")
    parser.add_argument("--scenarios", type=Path, default=SCENARIO_ROOT / "accepted_scenarios.jsonl")
    parser.add_argument("--query-families", type=Path, default=SCENARIO_ROOT / "query_families.jsonl")
    parser.add_argument("--output", type=Path, default=SCENARIO_ROOT / "query_variants.jsonl")
    args = parser.parse_args(arguments)
    scenarios = [AcceptedScenario.model_validate(record) for record in read_jsonl(args.scenarios)]
    families = [AuthoredQueryFamily.model_validate(record) for record in read_jsonl(args.query_families)]
    validate_query_corpus([scenario.scenario_id for scenario in scenarios], families)
    queries = [query for family in families for query in build_user_state_queries(family)]
    write_jsonl(args.output, queries)
    print(f"Wrote {len(queries)} approved query variants to {args.output}")


def _approve_query_protocol(arguments: List[str]) -> None:
    """Record explicit researcher approval for the authored query families."""
    parser = argparse.ArgumentParser(prog="risk-comm scenarios approve-query-protocol")
    parser.add_argument("--scenarios", type=Path, default=SCENARIO_ROOT / "accepted_scenarios.jsonl")
    parser.add_argument("--query-families", type=Path, default=SCENARIO_ROOT / "query_families.jsonl")
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--output", type=Path, default=SCENARIO_ROOT / "manual_revisions" / "query_protocol_approval.json")
    parser.add_argument("--confirm-query-protocol", action="store_true", required=True)
    args = parser.parse_args(arguments)
    scenarios = [AcceptedScenario.model_validate(record) for record in read_jsonl(args.scenarios)]
    families = [AuthoredQueryFamily.model_validate(record) for record in read_jsonl(args.query_families)]
    approval = build_query_protocol_approval(scenarios, families, args.approved_by, args.note)
    write_json(args.output, approval)
    print(f"Wrote query-protocol approval {approval.approval_sha256} to {args.output}")


def _apply_query_protocol(arguments: List[str]) -> None:
    """Republish accepted scenarios and their query variants from an exact approval."""
    parser = argparse.ArgumentParser(prog="risk-comm scenarios apply-query-protocol")
    parser.add_argument("--scenarios", type=Path, default=SCENARIO_ROOT / "accepted_scenarios.jsonl")
    parser.add_argument("--query-families", type=Path, default=SCENARIO_ROOT / "query_families.jsonl")
    parser.add_argument("--approval", type=Path, default=SCENARIO_ROOT / "manual_revisions" / "query_protocol_approval.json")
    parser.add_argument("--published-scenarios", type=Path, default=SCENARIO_ROOT / "accepted_scenarios.jsonl")
    parser.add_argument("--query-variants", type=Path, default=SCENARIO_ROOT / "query_variants.jsonl")
    args = parser.parse_args(arguments)
    scenarios = [AcceptedScenario.model_validate(record) for record in read_jsonl(args.scenarios)]
    families = [AuthoredQueryFamily.model_validate(record) for record in read_jsonl(args.query_families)]
    approval = QueryProtocolApproval.model_validate(read_json(args.approval))
    published, variants = apply_query_protocol(scenarios, families, approval)
    write_jsonl(args.published_scenarios, published)
    write_jsonl(args.query_variants, variants)
    print(f"Republished {len(published)} scenarios and {len(variants)} query variants")


def _approve_prompt_protocol(arguments: List[str]) -> None:
    """Record explicit approval for the six seed-owned evaluated-prompt contexts."""
    parser = argparse.ArgumentParser(prog="risk-comm scenarios approve-prompt-protocol")
    parser.add_argument("--seed-set", type=Path, default=SCENARIO_ROOT / "curated_scenario_generation_seeds.json")
    parser.add_argument("--scenarios", type=Path, default=SCENARIO_ROOT / "accepted_scenarios.jsonl")
    parser.add_argument("--prompt-contexts", type=Path, default=SCENARIO_ROOT / "prompt_contexts.json")
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--output", type=Path, default=SCENARIO_ROOT / "manual_revisions" / "prompt_protocol_approval.json")
    parser.add_argument("--confirm-prompt-protocol", action="store_true", required=True)
    args = parser.parse_args(arguments)
    seed_set = _load_seed_set(args.seed_set)
    scenario_records = read_jsonl(args.scenarios)
    context_set = PromptContextSet.model_validate(read_json(args.prompt_contexts))
    approval = build_prompt_protocol_approval(seed_set, scenario_records, context_set, args.approved_by, args.note)
    write_json(args.output, approval)
    print(f"Wrote prompt-protocol approval {approval.approval_sha256} to {args.output}")


def _apply_prompt_protocol(arguments: List[str]) -> None:
    """Publish the final seed and scenarios with approved role, task, and authority text."""
    parser = argparse.ArgumentParser(prog="risk-comm scenarios apply-prompt-protocol")
    parser.add_argument("--seed-set", type=Path, default=SCENARIO_ROOT / "curated_scenario_generation_seeds.json")
    parser.add_argument("--scenarios", type=Path, default=SCENARIO_ROOT / "accepted_scenarios.jsonl")
    parser.add_argument("--pending-scenarios", type=Path, default=SCENARIO_ROOT / "pending_scenarios.jsonl")
    parser.add_argument("--prompt-contexts", type=Path, default=SCENARIO_ROOT / "prompt_contexts.json")
    parser.add_argument("--approval", type=Path, default=SCENARIO_ROOT / "manual_revisions" / "prompt_protocol_approval.json")
    parser.add_argument("--final-seed-set", type=Path, default=SCENARIO_ROOT / "final_scenario_generation_seeds.json")
    parser.add_argument("--published-scenarios", type=Path, default=SCENARIO_ROOT / "accepted_scenarios.jsonl")
    args = parser.parse_args(arguments)
    seed_set = _load_seed_set(args.seed_set)
    scenario_records = read_jsonl(args.scenarios)
    context_set = PromptContextSet.model_validate(read_json(args.prompt_contexts))
    approval = PromptProtocolApproval.model_validate(read_json(args.approval))
    final_seed_set, scenarios = apply_prompt_protocol(seed_set, scenario_records, context_set, approval)
    pending = attach_prompt_contexts(read_jsonl(args.pending_scenarios), context_set)
    write_json(args.final_seed_set, final_seed_set)
    write_jsonl(args.published_scenarios, scenarios)
    write_jsonl(args.pending_scenarios, pending)
    print(f"Published seed-owned prompt contexts for {len(scenarios)} accepted scenarios")


def _assemble_generated(arguments: List[str]) -> None:
    """Join strict one-shot generator outputs to hidden metadata for researcher review."""
    parser = argparse.ArgumentParser(prog="risk-comm scenarios assemble-generated")
    parser.add_argument("--seed-set", type=Path, default=SCENARIO_ROOT / "scenario_generation_seeds.json")
    parser.add_argument("--generated-outputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=SCENARIO_ROOT / "pending_scenarios.jsonl")
    args = parser.parse_args(arguments)
    outputs = [GeneratedScenarioOutput.model_validate(record) for record in read_jsonl(args.generated_outputs)]
    scenarios = assemble_pending_corpus(_load_seed_set(args.seed_set), outputs)
    write_jsonl(args.output, scenarios)
    print(f"Assembled {len(scenarios)} pending scenarios for researcher review")


def _approve_curation(arguments: List[str]) -> None:
    """Bind explicit researcher approval to every documented manual correction."""
    parser = argparse.ArgumentParser(prog="risk-comm scenarios approve-curation")
    parser.add_argument("--seed-set", type=Path, default=SCENARIO_ROOT / "scenario_generation_seeds.json")
    parser.add_argument("--generated-outputs", type=Path, default=SCENARIO_ROOT / "generated_outputs.jsonl")
    parser.add_argument("--requests", type=Path, default=SCENARIO_ROOT / "generation_requests.jsonl")
    parser.add_argument("--manual-review", type=Path, default=SCENARIO_ROOT / "manual_review_audit.json")
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--output", type=Path, default=SCENARIO_ROOT / "manual_revisions" / "corpus_curation_approval.json")
    parser.add_argument("--confirm-researcher-curation", action="store_true", required=True)
    args = parser.parse_args(arguments)
    outputs = [GeneratedScenarioOutput.model_validate(record) for record in read_jsonl(args.generated_outputs)]
    approval = build_curation_approval(
        _load_seed_set(args.seed_set),
        outputs,
        _load_generation_requests(args.requests),
        read_json(args.manual_review),
        args.approved_by,
        args.note,
    )
    write_json(args.output, approval)
    print(f"Wrote corpus-curation approval {approval.curation_sha256} to {args.output}")


def _apply_curation(arguments: List[str]) -> None:
    """Apply approved corrections while preserving original request and response artifacts."""
    parser = argparse.ArgumentParser(prog="risk-comm scenarios apply-curation")
    parser.add_argument("--seed-set", type=Path, default=SCENARIO_ROOT / "scenario_generation_seeds.json")
    parser.add_argument("--generated-outputs", type=Path, default=SCENARIO_ROOT / "generated_outputs.jsonl")
    parser.add_argument("--requests", type=Path, default=SCENARIO_ROOT / "generation_requests.jsonl")
    parser.add_argument("--manual-review", type=Path, default=SCENARIO_ROOT / "manual_review_audit.json")
    parser.add_argument("--approval", type=Path, default=SCENARIO_ROOT / "manual_revisions" / "corpus_curation_approval.json")
    parser.add_argument("--curated-seed-set", type=Path, default=SCENARIO_ROOT / "curated_scenario_generation_seeds.json")
    parser.add_argument("--curated-outputs", type=Path, default=SCENARIO_ROOT / "curated_generated_outputs.jsonl")
    parser.add_argument("--pending-scenarios", type=Path, default=SCENARIO_ROOT / "pending_scenarios.jsonl")
    args = parser.parse_args(arguments)
    approval = CorpusCurationApproval.model_validate(read_json(args.approval))
    if artifact_sha256(read_json(args.manual_review)) != approval.manual_review_audit_sha256:
        raise PermissionError("curation approval belongs to a different manual-review audit")
    outputs = [GeneratedScenarioOutput.model_validate(record) for record in read_jsonl(args.generated_outputs)]
    curated_seed_set, curated_outputs, scenarios = assemble_curated_pending_corpus(
        _load_seed_set(args.seed_set),
        outputs,
        _load_generation_requests(args.requests),
        approval,
    )
    write_json(args.curated_seed_set, curated_seed_set)
    write_jsonl(args.curated_outputs, curated_outputs)
    write_jsonl(args.pending_scenarios, scenarios)
    print(f"Applied {len(approval.fact_text_edits)} fact edits and assembled {len(scenarios)} pending scenarios")


def main(command: str, arguments: List[str]) -> None:
    """Dispatch one scenario subcommand."""
    handlers = {
        "import-package": _import_package,
        "validate": _validate,
        "build-generation-requests": _build_generation_requests,
        "estimate-generation-cost": _estimate_generation_cost,
        "approve-generation": _approve_generation,
        "run-generation": _run_generation,
        "build-queries": _build_queries,
        "approve-query-protocol": _approve_query_protocol,
        "apply-query-protocol": _apply_query_protocol,
        "approve-prompt-protocol": _approve_prompt_protocol,
        "apply-prompt-protocol": _apply_prompt_protocol,
        "assemble-generated": _assemble_generated,
        "approve-curation": _approve_curation,
        "apply-curation": _apply_curation,
    }
    handlers[command](arguments)
