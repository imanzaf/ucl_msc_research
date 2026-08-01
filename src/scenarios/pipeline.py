"""Run the deliberately small initial scenario-generation pipeline."""

from __future__ import annotations

from typing import Dict, List, Mapping, Protocol, Tuple

from src.data_models.scenarios import AcceptedScenario, CandidateScenario, ScenarioReplicationSeed, ScenarioUseCaseSeed


class ScenarioGenerationBackend(Protocol):
    """Define the only model operation used by scenario generation."""

    def generate_candidate(
        self,
        use_case: ScenarioUseCaseSeed,
        replication: ScenarioReplicationSeed,
        fixed_c1_example: AcceptedScenario | None = None,
    ) -> CandidateScenario:
        """Generate one initial candidate from its seed and optional C1 example."""
        ...


def generate_initial_candidates(
    scenario_seeds: List[Tuple[ScenarioUseCaseSeed, ScenarioReplicationSeed]],
    backend: ScenarioGenerationBackend,
    c1_examples: Mapping[str, AcceptedScenario] | None = None,
) -> Dict[str, CandidateScenario]:
    """Generate each selected candidate once, with no review or revision calls."""
    if not scenario_seeds:
        raise ValueError("scenario generation selection cannot be empty")
    selected_ids = [replication.scenario_id for _, replication in scenario_seeds]
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("scenario generation selection contains duplicate identifiers")
    examples = c1_examples or {}
    generated: Dict[str, CandidateScenario] = {}
    for use_case, replication in scenario_seeds:
        is_calibration = replication.scenario_id.endswith("_C1")
        fixed_example = None if is_calibration else examples.get(use_case.use_case_id)
        if not is_calibration and fixed_example is None:
            raise ValueError(f"{replication.scenario_id} requires the matching published C1 generation example")
        if fixed_example is not None and not isinstance(fixed_example, AcceptedScenario):
            raise ValueError("R1/R2 generation examples must be published AcceptedScenario records")
        candidate = backend.generate_candidate(use_case, replication, fixed_c1_example=fixed_example)
        if candidate.scenario_id != replication.scenario_id or candidate.use_case_id != use_case.use_case_id:
            raise ValueError("generated candidate identity does not match its selected seed")
        generated[candidate.scenario_id] = candidate
    return generated
