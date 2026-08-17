"""Isolation, schema, layout, and manuscript-scope maintenance gates."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Type

from pydantic import BaseModel

from srcv2.experiments.planner import ExecutionBundle
from srcv2.models.experiments import RunUnit
from srcv2.models.manifests import CostApproval, PreflightApproval, ProtocolManifest, ScenarioGenerationApproval
from srcv2.models.queries import AuthoredQueryFamily, QueryVariant
from srcv2.models.scenarios import AcceptedScenario
from srcv2.models.scoring import (
    AccuracyJudgeOutput,
    ContentJudgeOutput,
    FactExtraction,
    FrozenJudgeContract,
    JudgeCallRecord,
    JudgeExecutionApproval,
    JudgeExecutionEstimate,
    JudgeOverride,
    JudgePilotSample,
    JudgeTask,
    PresentationJudgeOutput,
    SelectionOutcomes,
    SelectionRecoveryRecord,
)
from srcv2.paths import EXPERIMENT_NAMES, PROJECT_ROOT, SCHEMA_ROOT, experiment_paths
from srcv2.scenarios.curation import CorpusCurationApproval
from srcv2.scenarios.execution import ScenarioGenerationConfig, ScenarioGenerationRecord, ScenarioGenerationSummary
from srcv2.scenarios.generation import GeneratedScenarioOutput
from srcv2.scenarios.prompt_protocol import PromptContextSet, PromptProtocolApproval
from srcv2.scenarios.queries import QueryProtocolApproval
from srcv2.storage import atomic_write_bytes

SCHEMA_MODELS: Dict[str, Type[BaseModel]] = {
    "accepted_scenario": AcceptedScenario,
    "authored_query_family": AuthoredQueryFamily,
    "accuracy_judge_output": AccuracyJudgeOutput,
    "content_judge_output": ContentJudgeOutput,
    "cost_approval": CostApproval,
    "corpus_curation_approval": CorpusCurationApproval,
    "execution_bundle": ExecutionBundle,
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
    "run_unit": RunUnit,
    "scenario_generation_approval": ScenarioGenerationApproval,
    "scenario_generation_config": ScenarioGenerationConfig,
    "scenario_generation_record": ScenarioGenerationRecord,
    "scenario_generation_summary": ScenarioGenerationSummary,
    "selection_outcomes": SelectionOutcomes,
    "selection_recovery_record": SelectionRecoveryRecord,
}

PROHIBITED_MANUSCRIPT_TERMS = (
    "previous",
    "old",
    "revised",
    "redesign",
    "replacement",
    "legacy",
)


def validate_source_isolation(source_root: Path | None = None) -> List[str]:
    """Return every forbidden import of the historical package from final-protocol code."""
    root = source_root or PROJECT_ROOT / "srcv2"
    violations: List[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                violations.extend(
                    f"{path}:{node.lineno}: import {alias.name}" for alias in node.names if alias.name == "src" or alias.name.startswith("src.")
                )
            if isinstance(node, ast.ImportFrom) and node.module and (node.module == "src" or node.module.startswith("src.")):
                violations.append(f"{path}:{node.lineno}: from {node.module}")
    return violations


def validate_launchers(project_root: Path | None = None) -> List[str]:
    """Verify that the two launchers import only their respective CLI packages."""
    root = project_root or PROJECT_ROOT
    historical = (root / "scripts" / "risk-comm").read_text(encoding="utf-8")
    final = (root / "scripts" / "risk-comm-v2").read_text(encoding="utf-8")
    violations: List[str] = []
    if "from src.cli import main" not in historical:
        violations.append("risk-comm no longer imports src.cli")
    if "from srcv2.cli import main" not in final:
        violations.append("risk-comm-v2 does not import srcv2.cli")
    if re.search(r"from src\.cli|import src(?:\s|$)", final):
        violations.append("risk-comm-v2 references the historical package")
    return violations


def initialize_experiment_layout() -> List[Path]:
    """Create the required directories and stable placeholder asset for every experiment."""
    created: List[Path] = []
    for experiment in EXPERIMENT_NAMES:
        for name, path in experiment_paths(experiment).items():
            if name == "config":
                continue
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)
    return created


def export_json_schemas(schema_root: Path | None = None) -> List[Path]:
    """Synchronize the final-protocol public Pydantic schemas under a separate schema root."""
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


def validate_manuscript_language(manuscript_root: Path) -> List[str]:
    """Detect explicit historical-method comparison language in the final manuscript."""
    violations: List[str] = []
    for path in sorted(manuscript_root.rglob("*.tex")):
        lowered = path.read_text(encoding="utf-8").lower()
        violations.extend(f"{path}: contains '{term}'" for term in PROHIBITED_MANUSCRIPT_TERMS if re.search(rf"\b{re.escape(term)}\b", lowered))
        if re.search(r"\bv\d+(?:\.\d+){1,2}\b", lowered):
            violations.append(f"{path}: contains an internal semantic version label")
    return violations
