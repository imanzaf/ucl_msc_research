"""Export stable Draft 2020-12 JSON Schemas for all persisted V9 boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Type

from pydantic import BaseModel

from src.data_models.annotations import ConversationAnnotation
from src.data_models.experiments import CalibrationExperimentConfig, ConversationTranscript, ExperimentConfig, ModelSummary, RunUnit
from src.data_models.manifests import (
    AcceptedScenarioManifest,
    AmplePilotAttempt,
    AmplePilotRecord,
    AnalysisAssumptionInput,
    AnnotationSampleManifest,
    CalibrationExperimentManifest,
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
    ScoringExecutionManifest,
    SmallestEffectManifest,
    TightLimitManifest,
    WordBudgetManifest,
)
from src.data_models.scenario_review import ResearcherScenarioReview, ScenarioAcceptanceRecord, ScenarioPipelineDisposition, ScenarioReviewHistory
from src.data_models.scenarios import AcceptedScenario, CandidateScenario, MinimalCompleteResponse, ScenarioBlueprint, ScenarioSeedSet
from src.data_models.scoring import (
    AnalysisInputRow,
    AnalysisMissingnessReport,
    AnalysisSummary,
    ClaimAssessmentResult,
    ConditionBlindScoringInput,
    FactAnalysisInputRow,
    FactAssessmentResult,
    FailedConstructActionInput,
    ManualScoringQueueRecord,
    ManualScoringResolution,
    ResponseCommunicationResult,
    ScoredConversationBundle,
    ScoringExecutionAttempt,
    ScoringValidationReport,
)
from src.llm.openrouter import ProviderTextCacheRecord, ProviderTextResponse

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_MODELS: Dict[str, Type[BaseModel]] = {
    "accepted_scenario": AcceptedScenario,
    "accepted_scenario_manifest": AcceptedScenarioManifest,
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
    "condition_blind_scoring_input": ConditionBlindScoringInput,
    "conversation_annotation": ConversationAnnotation,
    "conversation_transcript": ConversationTranscript,
    "dry_run_cost_report": DryRunCostReport,
    "evaluated_model_manifest": EvaluatedModelManifest,
    "experiment_config": ExperimentConfig,
    "experiment_manifest": ExperimentManifest,
    "fact_assessment": FactAssessmentResult,
    "fact_analysis_input": FactAnalysisInputRow,
    "failed_construct_action_input": FailedConstructActionInput,
    "manual_scoring_queue_record": ManualScoringQueueRecord,
    "manual_scoring_resolution": ManualScoringResolution,
    "minimal_complete_response": MinimalCompleteResponse,
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
    "scenario_blueprint": ScenarioBlueprint,
    "scenario_candidate": CandidateScenario,
    "scenario_acceptance_record": ScenarioAcceptanceRecord,
    "scenario_pipeline_disposition": ScenarioPipelineDisposition,
    "scenario_review_history": ScenarioReviewHistory,
    "scenario_seed_set": ScenarioSeedSet,
    "scoring_validation_report": ScoringValidationReport,
    "scored_conversation_bundle": ScoredConversationBundle,
    "scoring_execution_attempt": ScoringExecutionAttempt,
    "scoring_execution_manifest": ScoringExecutionManifest,
    "smallest_effect_manifest": SmallestEffectManifest,
    "tight_limit_manifest": TightLimitManifest,
    "word_budget_manifest": WordBudgetManifest,
}


def main() -> None:
    """Write each strict boundary schema under schemas/v9/."""
    output_root = REPO_ROOT / "schemas" / "v9"
    output_root.mkdir(parents=True, exist_ok=True)
    for name, model in SCHEMA_MODELS.items():
        path = output_root / f"{name}.schema.json"
        payload = json.dumps(model.model_json_schema(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        path.write_text(payload, encoding="utf-8")
    print(f"Exported {len(SCHEMA_MODELS)} V9 schemas to {output_root}")


if __name__ == "__main__":
    main()
