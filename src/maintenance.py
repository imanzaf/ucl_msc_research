"""Schema export and experiment-layout maintenance helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Type

from pydantic import BaseModel

from src.analysis.commercial_interest import CommercialInterestContrast, CommercialInterestContrastSummary, CommercialInterestObservation
from src.experiments.planner import ExecutionBundle
from src.models.experiments import RunUnit
from src.models.manifests import CostApproval, PreflightApproval, ProtocolManifest, ScenarioGenerationApproval
from src.models.queries import AuthoredQueryFamily, QueryVariant
from src.models.scenarios import AcceptedScenario
from src.models.scoring import (
    AccuracyJudgeOutput,
    AdjudicatedJudgment,
    ContentJudgeOutput,
    ExperimentScoringManifest,
    FactExtraction,
    FrozenJudgeContract,
    JudgeCallRecord,
    JudgeExecutionApproval,
    JudgeExecutionEstimate,
    JudgeOverride,
    JudgePilotSample,
    JudgeTask,
    PresentationJudgeOutput,
    ResponseOutcomesRecord,
    SelectionOutcomes,
    SelectionRecoveryRecord,
)
from src.paths import EXPERIMENT_NAMES, SCHEMA_ROOT, experiment_paths
from src.scenarios.curation import CorpusCurationApproval
from src.scenarios.execution import ScenarioGenerationConfig, ScenarioGenerationRecord, ScenarioGenerationSummary
from src.scenarios.generation import GeneratedScenarioOutput
from src.scenarios.prompt_protocol import PromptContextSet, PromptProtocolApproval
from src.scenarios.queries import QueryProtocolApproval
from src.storage import atomic_write_bytes

SCHEMA_MODELS: Dict[str, Type[BaseModel]] = {
    "accepted_scenario": AcceptedScenario,
    "adjudicated_judgment": AdjudicatedJudgment,
    "authored_query_family": AuthoredQueryFamily,
    "accuracy_judge_output": AccuracyJudgeOutput,
    "content_judge_output": ContentJudgeOutput,
    "commercial_interest_contrast": CommercialInterestContrast,
    "commercial_interest_contrast_summary": CommercialInterestContrastSummary,
    "commercial_interest_observation": CommercialInterestObservation,
    "cost_approval": CostApproval,
    "corpus_curation_approval": CorpusCurationApproval,
    "execution_bundle": ExecutionBundle,
    "experiment_scoring_manifest": ExperimentScoringManifest,
    "fact_extraction": FactExtraction,
    "frozen_judge_contract": FrozenJudgeContract,
    "generated_scenario_output": GeneratedScenarioOutput,
    "judge_call_record": JudgeCallRecord,
    "judge_execution_approval": JudgeExecutionApproval,
    "judge_execution_estimate": JudgeExecutionEstimate,
    "judge_override": JudgeOverride,
    "judge_pilot_sample": JudgePilotSample,
    "judge_task": JudgeTask,
    "preflight_approval": PreflightApproval,
    "prompt_context_set": PromptContextSet,
    "prompt_protocol_approval": PromptProtocolApproval,
    "protocol_manifest": ProtocolManifest,
    "presentation_judge_output": PresentationJudgeOutput,
    "query_variant": QueryVariant,
    "query_protocol_approval": QueryProtocolApproval,
    "response_outcomes_record": ResponseOutcomesRecord,
    "run_unit": RunUnit,
    "scenario_generation_approval": ScenarioGenerationApproval,
    "scenario_generation_config": ScenarioGenerationConfig,
    "scenario_generation_record": ScenarioGenerationRecord,
    "scenario_generation_summary": ScenarioGenerationSummary,
    "selection_outcomes": SelectionOutcomes,
    "selection_recovery_record": SelectionRecoveryRecord,
}


def initialize_experiment_layout() -> List[Path]:
    """Create the required output directories for every retained experiment."""
    created: List[Path] = []
    for experiment in EXPERIMENT_NAMES:
        for name, path in experiment_paths(experiment).items():
            if name == "config":
                continue
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)
    return created


def export_json_schemas(schema_root: Path | None = None) -> List[Path]:
    """Synchronize the public Pydantic schemas under the canonical schema root."""
    root = schema_root or SCHEMA_ROOT
    root.mkdir(parents=True, exist_ok=True)
    outputs: List[Path] = []
    for name, model in SCHEMA_MODELS.items():
        path = root / f"{name}.schema.json"
        content = json.dumps(model.model_json_schema(), indent=2, sort_keys=True).encode("utf-8") + b"\n"
        atomic_write_bytes(path, content)
        outputs.append(path)
    expected = set(outputs)
    for path in root.glob("*.schema.json"):
        if path not in expected:
            path.unlink()
    return outputs
