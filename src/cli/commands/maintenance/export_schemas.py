"""Export stable Draft 2020-12 JSON Schemas for all persisted boundaries."""

from __future__ import annotations

import argparse
import json
from typing import Dict, Type

from pydantic import BaseModel

from src.data_models.annotations import ConversationAnnotation
from src.data_models.experiments import CalibrationExperimentConfig, ConversationTranscript, ExperimentConfig, ModelSummary, RunUnit
from src.data_models.manifests import (
    AcceptedScenarioManifest,
    AmplePilotApproval,
    AmplePilotAttempt,
    AmplePilotCostReport,
    AmplePilotRecord,
    AnalysisAssumptionInput,
    AnnotationSampleManifest,
    CalibrationExperimentManifest,
    CalibrationPromptReviewManifest,
    DryRunCostReport,
    EvaluatedModelManifest,
    ExperimentManifest,
    PaidExecutionApproval,
    PowerAssumptionManifest,
    PowerSimulationReport,
    PreregistrationManifest,
    PricingAssumptionInput,
    PromptReviewManifest,
    ProtocolDeviation,
    ProtocolDeviationManifest,
    ScenarioGenerationApproval,
    ScenarioGenerationCostReport,
    ScoringExecutionManifest,
    SmallestEffectManifest,
    TightLimitManifest,
    WordBudgetManifest,
)
from src.data_models.scenario_review import ResearcherScenarioReview, ScenarioAcceptanceRecord, ScenarioPipelineDisposition, ScenarioReviewHistory
from src.data_models.scenarios import AcceptedScenario, CandidateScenario, ScenarioSeedSet
from src.data_models.scoring import (
    AnalysisInputRow,
    AnalysisMissingnessReport,
    AnalysisSummary,
    ClaimAssessmentResult,
    ConditionBlindScoringInput,
    ConversationMetrics,
    DomainValidationGateManifest,
    FactAnalysisInputRow,
    FactAssessmentResult,
    ManualScoringQueueRecord,
    ManualScoringResolution,
    ResponseCommunicationResult,
    ScoredConversationBundle,
    ScoringExecutionAttempt,
    ScoringValidationReport,
    ValidationDispositionManifest,
)
from src.llm.openrouter import ProviderTextCacheRecord, ProviderTextResponse
from src.paths import REPO_ROOT

SCHEMA_MODELS: Dict[str, Type[BaseModel]] = {
    "accepted_scenario": AcceptedScenario,
    "accepted_scenario_manifest": AcceptedScenarioManifest,
    "ample_pilot_approval": AmplePilotApproval,
    "ample_pilot_cost_report": AmplePilotCostReport,
    "ample_pilot_record": AmplePilotRecord,
    "ample_pilot_attempt": AmplePilotAttempt,
    "analysis_input": AnalysisInputRow,
    "analysis_assumption_input": AnalysisAssumptionInput,
    "analysis_missingness_report": AnalysisMissingnessReport,
    "analysis_summary": AnalysisSummary,
    "annotation_sample_manifest": AnnotationSampleManifest,
    "claim_assessment": ClaimAssessmentResult,
    "calibration_experiment_config": CalibrationExperimentConfig,
    "calibration_experiment_manifest": CalibrationExperimentManifest,
    "calibration_prompt_review_manifest": CalibrationPromptReviewManifest,
    "condition_blind_scoring_input": ConditionBlindScoringInput,
    "conversation_annotation": ConversationAnnotation,
    "conversation_metrics": ConversationMetrics,
    "conversation_transcript": ConversationTranscript,
    "dry_run_cost_report": DryRunCostReport,
    "evaluated_model_manifest": EvaluatedModelManifest,
    "experiment_config": ExperimentConfig,
    "experiment_manifest": ExperimentManifest,
    "fact_assessment": FactAssessmentResult,
    "fact_analysis_input": FactAnalysisInputRow,
    "domain_validation_gate_manifest": DomainValidationGateManifest,
    "manual_scoring_queue_record": ManualScoringQueueRecord,
    "manual_scoring_resolution": ManualScoringResolution,
    "model_summary": ModelSummary,
    "paid_execution_approval": PaidExecutionApproval,
    "power_assumption_manifest": PowerAssumptionManifest,
    "power_simulation_report": PowerSimulationReport,
    "pricing_assumption_input": PricingAssumptionInput,
    "preregistration_manifest": PreregistrationManifest,
    "prompt_review_manifest": PromptReviewManifest,
    "protocol_deviation": ProtocolDeviation,
    "protocol_deviation_manifest": ProtocolDeviationManifest,
    "provider_text_cache_record": ProviderTextCacheRecord,
    "provider_text_response": ProviderTextResponse,
    "researcher_scenario_review": ResearcherScenarioReview,
    "response_communication": ResponseCommunicationResult,
    "run_unit": RunUnit,
    "scenario_candidate": CandidateScenario,
    "scenario_generation_approval": ScenarioGenerationApproval,
    "scenario_generation_cost_report": ScenarioGenerationCostReport,
    "scenario_acceptance_record": ScenarioAcceptanceRecord,
    "scenario_pipeline_disposition": ScenarioPipelineDisposition,
    "scenario_review_history": ScenarioReviewHistory,
    "scenario_seed_set": ScenarioSeedSet,
    "scoring_validation_report": ScoringValidationReport,
    "validation_disposition_manifest": ValidationDispositionManifest,
    "scored_conversation_bundle": ScoredConversationBundle,
    "scoring_execution_attempt": ScoringExecutionAttempt,
    "scoring_execution_manifest": ScoringExecutionManifest,
    "smallest_effect_manifest": SmallestEffectManifest,
    "tight_limit_manifest": TightLimitManifest,
    "word_budget_manifest": WordBudgetManifest,
}


def _add_seed_version_conditionals(schema: Dict[str, object]) -> Dict[str, object]:
    """Bind each immutable seed version to its exact active or archived use-case structure."""
    schema["allOf"] = [
        {
            "if": {"properties": {"schema_version": {"const": "0.9.0"}}, "required": ["schema_version"]},
            "then": {"properties": {"use_cases": {"items": {"$ref": "#/$defs/V09UseCaseSeed"}}}},
        },
        {
            "if": {"properties": {"schema_version": {"const": "0.8.0"}}, "required": ["schema_version"]},
            "then": {"properties": {"use_cases": {"items": {"$ref": "#/$defs/UseCaseSeed"}}}},
        },
        {
            "if": {"properties": {"schema_version": {"const": "0.7.0"}}, "required": ["schema_version"]},
            "then": {"properties": {"use_cases": {"items": {"$ref": "#/$defs/V07UseCaseSeed"}}}},
        },
        {
            "if": {"properties": {"schema_version": {"const": "0.6.0"}}, "required": ["schema_version"]},
            "then": {
                "properties": {
                    "use_cases": {
                        "items": {
                            "allOf": [
                                {"$ref": "#/$defs/LegacyUseCaseSeed"},
                                {"required": ["decision_conflict"], "not": {"required": ["potential_harm_pathway"]}},
                            ]
                        }
                    }
                }
            },
        },
        {
            "if": {"properties": {"schema_version": {"enum": ["0.5.1", "0.5.2"]}}, "required": ["schema_version"]},
            "then": {
                "properties": {
                    "use_cases": {
                        "items": {
                            "allOf": [
                                {"$ref": "#/$defs/LegacyUseCaseSeed"},
                                {"required": ["potential_harm_pathway"], "not": {"required": ["decision_conflict"]}},
                            ]
                        }
                    }
                }
            },
        },
    ]
    return schema


def main() -> None:
    """Write each strict boundary schema under schemas/."""
    argparse.ArgumentParser().parse_args()
    output_root = REPO_ROOT / "schemas"
    output_root.mkdir(parents=True, exist_ok=True)
    for name, model in SCHEMA_MODELS.items():
        path = output_root / f"{name}.schema.json"
        schema = model.model_json_schema()
        if model is ScenarioSeedSet:
            schema = _add_seed_version_conditionals(schema)
        payload = json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        path.write_text(payload, encoding="utf-8")
    print(f"Exported {len(SCHEMA_MODELS)} schemas to {output_root}")


if __name__ == "__main__":
    main()
