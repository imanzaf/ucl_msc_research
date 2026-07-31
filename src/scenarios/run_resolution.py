"""Resolve current scenario artifacts across timestamped rounds of one named run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from src.data_models.scenario_review import ResearcherScenarioReview
from src.data_models.scenarios import CandidateScenario
from src.paths import SCENARIO_ROUND_ID_PATTERN
from src.scenarios.acceptance import validate_candidate_scenario_hash
from src.scenarios.candidate_compatibility import read_candidate_scenario
from src.storage import read_model_jsonl


@dataclass(frozen=True)
class CurrentScenarioArtifact:
    """Locate the newest generated version of one scenario within a named run."""

    round_id: str
    round_root: Path
    candidate_path: Path
    automated_reviews_path: Path
    revision_cycles_path: Path
    terminal_decision_path: Path
    candidate: CandidateScenario


def scenario_round_roots(run_root: Path) -> List[Path]:
    """Return timestamped round directories in chronological order."""
    if not run_root.is_dir():
        raise FileNotFoundError(f"scenario generation run does not exist: {run_root}")
    return sorted(path for path in run_root.iterdir() if path.is_dir() and SCENARIO_ROUND_ID_PATTERN.fullmatch(path.name) is not None)


def current_scenario_artifacts(run_root: Path) -> Dict[str, CurrentScenarioArtifact]:
    """Select the newest generated candidate path for every scenario identifier."""
    current: Dict[str, CurrentScenarioArtifact] = {}
    for round_root in scenario_round_roots(run_root):
        for candidate_path in sorted((round_root / "scenarios").glob("CF???_*/candidate.json")):
            candidate = read_candidate_scenario(candidate_path)
            if candidate_path.parent.name != candidate.scenario_id:
                raise ValueError(f"candidate directory does not match scenario id: {candidate_path}")
            validate_candidate_scenario_hash(candidate)
            current[candidate.scenario_id] = CurrentScenarioArtifact(
                round_id=round_root.name,
                round_root=round_root,
                candidate_path=candidate_path,
                automated_reviews_path=candidate_path.parent / "automated_reviews.jsonl",
                revision_cycles_path=candidate_path.parent / "revision_cycles.jsonl",
                terminal_decision_path=candidate_path.parent / "terminal_decision.json",
                candidate=candidate,
            )
    return current


def run_researcher_reviews(run_root: Path) -> List[ResearcherScenarioReview]:
    """Load the append-only review history shared by every round in one run."""
    reviews = []
    for review_path in sorted((run_root / "researcher_review").glob("*.jsonl")):
        reviews.extend(read_model_jsonl(review_path, ResearcherScenarioReview))
    return reviews


def reviews_by_artifact_hash(run_root: Path) -> Dict[str, ResearcherScenarioReview]:
    """Index researcher decisions by immutable candidate hash and reject duplicates."""
    indexed: Dict[str, ResearcherScenarioReview] = {}
    for review in run_researcher_reviews(run_root):
        if review.reviewed_artifact_sha256 in indexed:
            raise ValueError(f"duplicate researcher decision for candidate hash {review.reviewed_artifact_sha256}")
        indexed[review.reviewed_artifact_sha256] = review
    return indexed


def current_researcher_review(
    artifact: CurrentScenarioArtifact,
    reviews_by_hash: Dict[str, ResearcherScenarioReview],
) -> Optional[ResearcherScenarioReview]:
    """Return the researcher decision bound to one current candidate, if present."""
    review = reviews_by_hash.get(artifact.candidate.candidate_sha256)
    if review is not None and review.scenario_id != artifact.candidate.scenario_id:
        raise ValueError("researcher review scenario id does not match its candidate hash")
    return review
