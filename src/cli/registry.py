"""Lazy command registry for the study workflows."""

from __future__ import annotations

from typing import NamedTuple


class Command(NamedTuple):
    """Register one lazily imported command."""

    module: str
    help: str


COMMAND_GROUPS = {
    "scenarios": {
        "import-package": Command("src.cli.commands.scenarios", "Verify, preserve, correct, and import the supplied scenario package."),
        "validate": Command("src.cli.commands.scenarios", "Audit seed or accepted corpus invariants."),
        "build-generation-requests": Command("src.cli.commands.scenarios", "Build one immutable fact-generation request per scenario."),
        "estimate-generation-cost": Command("src.cli.commands.scenarios", "Estimate the pinned GPT-5.4 fact-generation cost."),
        "approve-generation": Command("src.cli.commands.scenarios", "Record bounded approval for paid fact generation."),
        "run-generation": Command("src.cli.commands.scenarios", "Run or resume the approved one-shot fact generation."),
        "approve-curation": Command("src.cli.commands.scenarios", "Bind researcher approval to documented corpus corrections."),
        "apply-curation": Command("src.cli.commands.scenarios", "Apply approved corrections while preserving generation provenance."),
        "approve-query-protocol": Command("src.cli.commands.scenarios", "Bind approval to the six natural queries for every scenario."),
        "apply-query-protocol": Command("src.cli.commands.scenarios", "Republish accepted scenarios with approved natural queries."),
        "approve-prompt-protocol": Command("src.cli.commands.scenarios", "Bind approval to seed-owned roles, tasks, and authority limits."),
        "apply-prompt-protocol": Command("src.cli.commands.scenarios", "Publish approved seed-owned evaluated-prompt contexts."),
        "build-queries": Command("src.cli.commands.scenarios", "Build the six controlled affect-by-length query variants."),
        "assemble-generated": Command("src.cli.commands.scenarios", "Validate generated facts and join hidden metadata for review."),
    },
    "experiment": {
        "build-plan": Command("src.cli.commands.experiment", "Build the 10,710-unit active run matrix."),
        "approve-preflight": Command("src.cli.commands.experiment", "Record bounded approval for paid compatibility probes."),
        "preflight": Command("src.cli.commands.experiment", "Probe approved model/provider routes before freezing."),
        "freeze-protocol": Command("src.cli.commands.experiment", "Freeze preflighted model and provider snapshots."),
        "estimate-cost": Command("src.cli.commands.experiment", "Record a transparent current-pricing cost estimate."),
        "build-bundles": Command("src.cli.commands.experiment", "Materialize accepted scenarios into frozen execution bundles."),
        "approve-execution": Command("src.cli.commands.experiment", "Record bounded approval for evaluated paid execution."),
        "execute-unit": Command("src.cli.commands.experiment", "Execute one approved frozen run unit."),
        "execute-batch": Command("src.cli.commands.experiment", "Execute or resume one approved experiment batch with cost accounting."),
    },
    "scoring": {
        "sample-pilot": Command("src.cli.commands.scoring", "Draw one experiment's stratified five-percent judge-development sample."),
        "show-prompts": Command("src.cli.commands.scoring", "Write the three exact Gemini 3.1 Flash Lite judge contracts for review."),
        "recover-selections": Command("src.cli.commands.scoring", "Recover unambiguous exact-budget selections without changing adherence."),
        "build-plan": Command("src.cli.commands.scoring", "Build the pilot or full eight-call-per-response judge plan."),
        "estimate-cost": Command("src.cli.commands.scoring", "Estimate one exact judge plan using current token prices."),
        "approve-execution": Command("src.cli.commands.scoring", "Approve paid execution of one exact judge plan."),
        "execute-pilot": Command("src.cli.commands.scoring", "Run or resume the approved judge-development pilot."),
        "merge-results": Command("src.cli.commands.scoring", "Merge reusable and replacement raw judge records into one ordered result."),
        "freeze-contract": Command("src.cli.commands.scoring", "Freeze all three contracts after pilot review."),
        "execute-full": Command("src.cli.commands.scoring", "Run all frozen judges over every evaluated response."),
        "apply-overrides": Command("src.cli.commands.scoring", "Apply auditable manual corrections to raw judge labels."),
        "calculate-outcomes": Command("src.cli.commands.scoring", "Write one experiment's final response scores and scoring manifest."),
    },
    "analysis": {
        "confirmatory": Command("src.cli.commands.analysis", "Run seven directional tests with multiplicity control within research questions."),
        "commercial-interest-observations": Command(
            "src.cli.commands.analysis", "Prepare complete matched observations from commercial-interest response outcomes."
        ),
        "commercial-interest": Command("src.cli.commands.analysis", "Calculate matched commercial-interest instruction contrasts."),
        "option-first-choices": Command("src.cli.commands.analysis", "Derive forced-choice-specific labels from frozen presentation outcomes."),
    },
    "maintenance": {
        "export-schemas": Command("src.cli.commands.maintenance", "Export the public schemas under schemas/."),
        "initialize-layout": Command("src.cli.commands.maintenance", "Create complete experiment output layouts."),
    },
    "review": {
        "scenario-status": Command("src.cli.commands.review", "Summarize one-pass scenario review dispositions."),
        "accept-curated-scenarios": Command("src.cli.commands.review", "Record acceptance of the complete curated scenario corpus."),
        "publish-scenarios": Command("src.cli.commands.review", "Publish only scenarios with one accepted researcher review."),
        "judge-status": Command("src.cli.commands.review", "Summarize judge-pilot results and contract state."),
    },
}
