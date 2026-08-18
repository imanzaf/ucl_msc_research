"""Lazy command registry containing only final-protocol modules."""

from __future__ import annotations

from typing import NamedTuple


class Command(NamedTuple):
    """Register one lazily imported final-protocol command."""

    module: str
    help: str


COMMAND_GROUPS = {
    "scenarios": {
        "import-package": Command("srcv2.cli.commands.scenarios", "Verify, preserve, correct, and import the supplied scenario package."),
        "validate": Command("srcv2.cli.commands.scenarios", "Audit seed or accepted corpus invariants."),
        "build-generation-requests": Command("srcv2.cli.commands.scenarios", "Build one immutable fact-generation request per scenario."),
        "estimate-generation-cost": Command("srcv2.cli.commands.scenarios", "Estimate the pinned GPT-5.4 fact-generation cost."),
        "approve-generation": Command("srcv2.cli.commands.scenarios", "Record bounded approval for paid fact generation."),
        "run-generation": Command("srcv2.cli.commands.scenarios", "Run or resume the approved one-shot fact generation."),
        "approve-curation": Command("srcv2.cli.commands.scenarios", "Bind researcher approval to documented corpus corrections."),
        "apply-curation": Command("srcv2.cli.commands.scenarios", "Apply approved corrections while preserving generation provenance."),
        "approve-query-protocol": Command("srcv2.cli.commands.scenarios", "Bind approval to the six natural queries for every scenario."),
        "apply-query-protocol": Command("srcv2.cli.commands.scenarios", "Republish accepted scenarios with approved natural queries."),
        "approve-prompt-protocol": Command("srcv2.cli.commands.scenarios", "Bind approval to seed-owned roles, tasks, and authority limits."),
        "apply-prompt-protocol": Command("srcv2.cli.commands.scenarios", "Publish approved seed-owned evaluated-prompt contexts."),
        "build-queries": Command("srcv2.cli.commands.scenarios", "Build the six controlled affect-by-length query variants."),
        "assemble-generated": Command("srcv2.cli.commands.scenarios", "Validate generated facts and join hidden metadata for review."),
    },
    "experiment": {
        "build-plan": Command("srcv2.cli.commands.experiment", "Build the 10,710-unit active run matrix."),
        "approve-preflight": Command("srcv2.cli.commands.experiment", "Record bounded approval for paid compatibility probes."),
        "preflight": Command("srcv2.cli.commands.experiment", "Probe approved model/provider routes before freezing."),
        "freeze-protocol": Command("srcv2.cli.commands.experiment", "Freeze preflighted model and provider snapshots."),
        "estimate-cost": Command("srcv2.cli.commands.experiment", "Record a transparent current-pricing cost estimate."),
        "build-bundles": Command("srcv2.cli.commands.experiment", "Materialize accepted scenarios into frozen execution bundles."),
        "approve-execution": Command("srcv2.cli.commands.experiment", "Record bounded approval for evaluated paid execution."),
        "execute-unit": Command("srcv2.cli.commands.experiment", "Execute one approved frozen run unit."),
        "execute-batch": Command("srcv2.cli.commands.experiment", "Execute or resume one approved experiment batch with cost accounting."),
        "generate-assets": Command("srcv2.cli.commands.experiment", "Generate stable paper assets for every experiment."),
    },
    "scoring": {
        "sample-pilot": Command("srcv2.cli.commands.scoring", "Draw one experiment's stratified five-percent judge-development sample."),
        "show-prompts": Command("srcv2.cli.commands.scoring", "Write the three exact Gemini 3.1 Flash Lite judge contracts for review."),
        "recover-selections": Command("srcv2.cli.commands.scoring", "Recover unambiguous exact-budget selections without changing adherence."),
        "build-plan": Command("srcv2.cli.commands.scoring", "Build the pilot or full eight-call-per-response judge plan."),
        "estimate-cost": Command("srcv2.cli.commands.scoring", "Estimate one exact judge plan using current token prices."),
        "approve-execution": Command("srcv2.cli.commands.scoring", "Approve paid execution of one exact judge plan."),
        "execute-pilot": Command("srcv2.cli.commands.scoring", "Run or resume the approved judge-development pilot."),
        "merge-results": Command("srcv2.cli.commands.scoring", "Merge reusable and replacement raw judge records into one ordered result."),
        "freeze-contract": Command("srcv2.cli.commands.scoring", "Freeze all three contracts after pilot review."),
        "execute-full": Command("srcv2.cli.commands.scoring", "Run all frozen judges over every evaluated response."),
        "apply-overrides": Command("srcv2.cli.commands.scoring", "Apply auditable manual corrections to raw judge labels."),
        "calculate-outcomes": Command("srcv2.cli.commands.scoring", "Write one experiment's final response scores and scoring manifest."),
    },
    "analysis": {
        "confirmatory": Command("srcv2.cli.commands.analysis", "Run only the two Holm-corrected confirmatory contrasts."),
        "describe": Command("srcv2.cli.commands.analysis", "Summarize use-case or access groups descriptively."),
        "commercial-interest-observations": Command(
            "srcv2.cli.commands.analysis", "Prepare complete matched observations from commercial-interest response outcomes."
        ),
        "commercial-interest": Command("srcv2.cli.commands.analysis", "Calculate matched commercial-interest instruction contrasts."),
    },
    "maintenance": {
        "export-schemas": Command("srcv2.cli.commands.maintenance", "Export final-protocol schemas under schemas_v2."),
        "initialize-layout": Command("srcv2.cli.commands.maintenance", "Create complete experiment output layouts."),
        "validate-isolation": Command("srcv2.cli.commands.maintenance", "Reject historical-package imports and launcher crossover."),
        "validate-manuscript": Command("srcv2.cli.commands.maintenance", "Reject historical-comparison language in the final manuscript."),
    },
    "review": {
        "scenario-status": Command("srcv2.cli.commands.review", "Summarize one-pass scenario review dispositions."),
        "accept-curated-scenarios": Command("srcv2.cli.commands.review", "Record acceptance of the complete curated scenario corpus."),
        "publish-scenarios": Command("srcv2.cli.commands.review", "Publish only scenarios with one accepted researcher review."),
        "judge-status": Command("srcv2.cli.commands.review", "Summarize judge-pilot results and contract state."),
    },
}
