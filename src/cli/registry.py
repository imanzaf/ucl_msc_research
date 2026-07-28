"""Declare the public command names exposed by the unified CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class Command:
    """Describe an importable command and its purpose."""

    module: str
    help: str


COMMAND_GROUPS: Dict[str, Dict[str, Command]] = {
    "scenarios": {
        "generate": Command("src.cli.commands.scenarios.generate", "Generate and review scenario candidates."),
        "publish": Command("src.cli.commands.scenarios.publish", "Publish a run's accepted scenarios and set manifest."),
        "build-manifest": Command("src.cli.commands.scenarios.build_manifest", "Build the accepted-scenario manifest."),
        "freeze-tight-limits": Command("src.cli.commands.scenarios.freeze_tight_limits", "Freeze tight word limits from pilot outputs."),
        "finalize-word-budgets": Command("src.cli.commands.scenarios.finalize_word_budgets", "Finalize the word-budget manifest."),
    },
    "calibration": {
        "dry-run-ample-pilot": Command(
            "src.cli.commands.calibration.dry_run_ample_pilot",
            "Create the ample-pilot cost report.",
        ),
        "approve-ample-pilot": Command(
            "src.cli.commands.calibration.approve_ample_pilot",
            "Record explicit ample-pilot cost approval.",
        ),
        "run-ample-pilot": Command("src.cli.commands.calibration.run_ample_pilot", "Run the ample-condition pilot."),
        "run-c1": Command("src.cli.commands.calibration.run_c1", "Run or resume the one-model C1 2×2 diagnostic."),
        "build-plan": Command("src.cli.commands.calibration.build_plan", "Build the calibration run plan."),
        "run": Command("src.cli.commands.calibration.run", "Run the calibration experiment."),
        "assets": Command("src.cli.commands.calibration.assets", "Generate calibration paper assets."),
    },
    "experiment": {
        "freeze-models": Command("src.cli.commands.experiment.freeze_models", "Freeze evaluated model metadata."),
        "freeze-calibration-prompts": Command(
            "src.cli.commands.experiment.freeze_calibration_prompts",
            "Freeze the twenty reviewed C1 requests before the ample pilot.",
        ),
        "freeze-prompts": Command("src.cli.commands.experiment.freeze_prompts", "Freeze reviewed prompt packages."),
        "build-manifests": Command("src.cli.commands.experiment.build_manifests", "Build experiment manifests."),
        "build-plan": Command("src.cli.commands.experiment.build_plan", "Build the reviewed experiment run plan."),
        "build-exploratory-plans": Command(
            "src.cli.commands.experiment.build_exploratory_plans",
            "Build the two separately manifested exploratory run plans.",
        ),
        "preregister": Command("src.cli.commands.experiment.preregister", "Build the preregistration manifest."),
        "dry-run": Command("src.cli.commands.experiment.dry_run", "Create the dry-run cost report."),
        "approve": Command("src.cli.commands.experiment.approve", "Record paid-execution approval."),
        "finalize-deviations": Command("src.cli.commands.experiment.finalize_deviations", "Finalize protocol deviations."),
        "run": Command("src.cli.commands.experiment.run", "Run the reviewed experiment."),
        "summarize": Command("src.cli.commands.experiment.summarize", "Summarize experiment outputs."),
    },
    "scoring": {
        "build-manifest": Command("src.cli.commands.scoring.build_manifest", "Build the scoring execution manifest."),
        "run-c1": Command("src.cli.commands.scoring.run_c1", "Score the one-model C1 2×2 diagnostic."),
        "validate-c1": Command(
            "src.cli.commands.scoring.validate_c1",
            "Validate redesigned C1 outputs before scoring freeze.",
        ),
        "run": Command("src.cli.commands.scoring.run", "Score experiment outputs."),
        "resolve-manual": Command("src.cli.commands.scoring.resolve_manual", "Resolve records routed to manual scoring."),
        "validate": Command("src.cli.commands.scoring.validate", "Build the scoring validation report."),
        "freeze-validation-gates": Command(
            "src.cli.commands.scoring.freeze_validation_gates",
            "Freeze calibration-derived construct validation gates.",
        ),
        "record-validation-disposition": Command(
            "src.cli.commands.scoring.record_validation_disposition",
            "Record blinded failed-construct contingencies.",
        ),
        "sample-annotations": Command("src.cli.commands.scoring.sample_annotations", "Build the annotation sample."),
        "build-human-reference": Command("src.cli.commands.scoring.build_human_reference", "Build human-reference analysis inputs."),
    },
    "analysis": {
        "freeze-assumptions": Command("src.cli.commands.analysis.freeze_assumptions", "Freeze analysis assumptions."),
        "simulate-power": Command("src.cli.commands.analysis.simulate_power", "Run the power simulation."),
        "build-inputs": Command("src.cli.commands.analysis.build_inputs", "Build analysis-ready inputs."),
        "run": Command("src.cli.commands.analysis.run", "Run the registered analysis."),
        "run-exploratory": Command(
            "src.cli.commands.analysis.run_exploratory",
            "Run paired exploratory analyses without confirmatory p-values.",
        ),
        "assets": Command("src.cli.commands.analysis.assets", "Generate paper-ready analysis assets."),
    },
    "maintenance": {
        "export-schemas": Command("src.cli.commands.maintenance.export_schemas", "Export committed JSON schemas."),
        "validate-protocol": Command("src.cli.commands.maintenance.validate_protocol", "Validate protocol artifacts."),
        "validate-docs": Command("src.cli.commands.maintenance.validate_docs", "Check active documentation commands and paths."),
    },
    "review": {
        "launch": Command("src.cli.commands.review.launch", "Launch the local review application."),
    },
}
