"""Build six-construct validation diagnostics from blinded annotations."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from src.cli.commands.scoring.resolve_manual import build_manual_results
from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256, file_sha256, validate_model_self_hash
from src.data_models.experiments import ConversationTranscript
from src.data_models.manifests import AcceptedScenarioManifest, AnnotationSampleManifest
from src.data_models.scoring import (
    ConstructValidationDiagnostics,
    ConstructValidationGateManifest,
    EvaluationCheckpoint,
    PresentationFinding,
    ScoredConversationBundle,
    ScoredResponse,
    ScoringConstruct,
)
from src.experiments.io import load_all_accepted_scenarios
from src.scoring.annotation_resolution import final_annotations
from src.scoring.metrics import compute_conversation_metrics
from src.scoring.reliability import build_construct_validation_diagnostics, build_scoring_validation_report
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic


def _invalid_counts(path: Path | None) -> Dict[ScoringConstruct, int]:
    """Load optional per-contract invalid-output counts."""
    if path is None:
        return {construct: 0 for construct in ScoringConstruct}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {construct.value for construct in ScoringConstruct}:
        raise ValueError("invalid-output counts must contain all six scoring constructs")
    counts = {ScoringConstruct(name): int(value) for name, value in payload.items()}
    if any(value < 0 for value in counts.values()):
        raise ValueError("invalid-output counts cannot be negative")
    return counts


def _presentation_key(
    response: ScoredResponse,
    finding: PresentationFinding,
) -> str:
    """Encode behavior, direction, target, and exact grounded evidence."""
    return "|".join(
        [
            response.value,
            finding.fact_id,
            finding.behaviour.value,
            finding.direction.value,
            finding.evidence,
        ]
    )


def _append_binary_set_labels(
    reference_items: Sequence[str],
    predicted_items: Sequence[str],
    reference: List[str],
    predicted: List[str],
    clusters: List[str],
    blind_id: str,
) -> None:
    """Append presence decisions over the union of two finding sets."""
    reference_set = set(reference_items)
    predicted_set = set(predicted_items)
    items = sorted(reference_set | predicted_set) or ["no_finding"]
    for item in items:
        reference.append("present" if item in reference_set else "absent")
        predicted.append("present" if item in predicted_set else "absent")
        clusters.append(blind_id)


def _collect_construct_labels(
    sample: AnnotationSampleManifest,
    annotations: Dict[str, ConversationAnnotation],
    bundles: Dict[str, ScoredConversationBundle],
    transcripts: Dict[str, ConversationTranscript],
    scenarios: Dict[str, object],
) -> Tuple[
    Dict[ScoringConstruct, List[str]],
    Dict[ScoringConstruct, List[str]],
    Dict[ScoringConstruct, List[str]],
    Dict[ScoringConstruct, Decimal | None],
]:
    """Collect binary labels plus ordering/emphasis absolute errors."""
    references = {construct: [] for construct in ScoringConstruct}
    predictions = {construct: [] for construct in ScoringConstruct}
    clusters = {construct: [] for construct in ScoringConstruct}
    errors: Dict[ScoringConstruct, List[Decimal]] = {
        ScoringConstruct.ORDERING: [],
        ScoringConstruct.EMPHASIS: [],
    }
    for blind_id in sample.conversation_ids:
        annotation = annotations[blind_id]
        bundle = bundles[blind_id]
        transcript = transcripts[bundle.run_unit_id]
        scenario = scenarios[transcript.run_unit.scenario_id]
        human_content, human_presentation, human_accuracy = build_manual_results(
            annotation,
            bundle.scoring_inputs,
            transcript,
        )
        for response in ScoredResponse:
            human_facts = {item.fact_id: item for item in human_content[response].judgments}
            judged_facts = {item.fact_id: item for item in bundle.content_results[response].judgments}
            if set(human_facts) != set(judged_facts):
                raise ValueError("human and automated fact decisions differ in scope")
            for fact_id in sorted(human_facts):
                human_fact = human_facts[fact_id]
                judged_fact = judged_facts[fact_id]
                references[ScoringConstruct.COVERAGE].append("present" if human_fact.present else "absent")
                predictions[ScoringConstruct.COVERAGE].append("present" if judged_fact.present else "absent")
                clusters[ScoringConstruct.COVERAGE].append(blind_id)
                human_markers = {item.element_id: item for item in human_fact.marker_judgments}
                judged_markers = {item.element_id: item for item in judged_fact.marker_judgments}
                if set(human_markers) != set(judged_markers):
                    raise ValueError("human and automated marker decisions differ in scope")
                for element_id in sorted(human_markers):
                    references[ScoringConstruct.SPECIFICITY].append("present" if human_markers[element_id].present else "absent")
                    predictions[ScoringConstruct.SPECIFICITY].append("present" if judged_markers[element_id].present else "absent")
                    clusters[ScoringConstruct.SPECIFICITY].append(blind_id)
            _append_binary_set_labels(
                [_presentation_key(response, finding) for finding in human_presentation[response].findings],
                [_presentation_key(response, finding) for finding in bundle.presentation_results[response].findings],
                references[ScoringConstruct.FRAMING],
                predictions[ScoringConstruct.FRAMING],
                clusters[ScoringConstruct.FRAMING],
                blind_id,
            )
            references[ScoringConstruct.ACCURACY].append("present" if human_accuracy[response].false_claim_present else "absent")
            predictions[ScoringConstruct.ACCURACY].append("present" if bundle.accuracy_results[response].false_claim_present else "absent")
            clusters[ScoringConstruct.ACCURACY].append(blind_id)

        human_metrics = {
            checkpoint: compute_conversation_metrics(
                transcript,
                scenario,
                human_content,
                human_presentation,
                human_accuracy,
                checkpoint,
            )
            for checkpoint in EvaluationCheckpoint
        }
        judged_metrics = {metric.checkpoint: metric for metric in bundle.metrics}
        for checkpoint in EvaluationCheckpoint:
            for construct, field in [
                (ScoringConstruct.ORDERING, "ordering_asymmetry"),
                (ScoringConstruct.EMPHASIS, "emphasis_asymmetry"),
            ]:
                human_value = getattr(human_metrics[checkpoint], field)
                judged_value = getattr(judged_metrics[checkpoint], field)
                references[construct].append(str(human_value))
                predictions[construct].append(str(judged_value))
                clusters[construct].append(blind_id)
                errors[construct].append(abs(human_value - judged_value))
    maximum_errors: Dict[ScoringConstruct, Decimal | None] = {
        construct: (max(errors[construct]) if construct in errors and errors[construct] else None) for construct in ScoringConstruct
    }
    return references, predictions, clusters, maximum_errors


def main() -> None:
    """Calculate and persist blinded diagnostics under calibration-frozen gates."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotation-sample-manifest", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--scored-bundles", type=Path, required=True)
    parser.add_argument("--source-transcripts", type=Path, required=True)
    parser.add_argument("--accepted-root", type=Path, required=True)
    parser.add_argument("--accepted-scenario-manifest", type=Path, required=True)
    parser.add_argument("--construct-gate-manifest", type=Path, required=True)
    parser.add_argument("--invalid-output-counts", type=Path)
    parser.add_argument("--bootstrap-seed", type=int, default=7)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sample = read_model_json(
        args.annotation_sample_manifest,
        AnnotationSampleManifest,
    )
    gates = read_model_json(
        args.construct_gate_manifest,
        ConstructValidationGateManifest,
    )
    accepted_manifest = read_model_json(
        args.accepted_scenario_manifest,
        AcceptedScenarioManifest,
    )
    for manifest in [sample, gates, accepted_manifest]:
        validate_model_self_hash(manifest, "manifest_sha256")
    if sample.source_transcripts_sha256 != file_sha256(args.source_transcripts):
        raise ValueError("annotation sample does not bind the transcript bytes")
    annotations = final_annotations(
        sample,
        read_model_jsonl(args.annotations, ConversationAnnotation),
    )
    all_bundles = read_model_jsonl(
        args.scored_bundles,
        ScoredConversationBundle,
    )
    bundles = {
        next(iter(bundle.scoring_inputs.values())).blind_conversation_id: bundle
        for bundle in all_bundles
        if next(iter(bundle.scoring_inputs.values())).blind_conversation_id in set(sample.conversation_ids)
    }
    if set(bundles) != set(sample.conversation_ids):
        raise ValueError("scored bundles must cover the frozen annotation sample")
    for blind_id, annotation in annotations.items():
        if annotation.scoring_input_sha256 != artifact_sha256(bundles[blind_id].scoring_inputs):
            raise ValueError("human and automated scoring use different isolated inputs")
    transcripts = {
        transcript.run_unit.run_unit_id: transcript
        for transcript in read_model_jsonl(
            args.source_transcripts,
            ConversationTranscript,
        )
    }
    scenarios = {
        scenario.scenario_id: scenario
        for scenario in load_all_accepted_scenarios(
            args.accepted_root,
            accepted_manifest,
        )
    }
    references, predictions, clusters, maximum_errors = _collect_construct_labels(
        sample,
        annotations,
        bundles,
        transcripts,
        scenarios,
    )
    invalid_counts = _invalid_counts(args.invalid_output_counts)
    diagnostics: Dict[ScoringConstruct, ConstructValidationDiagnostics] = {}
    for index, construct in enumerate(ScoringConstruct):
        diagnostics[construct] = build_construct_validation_diagnostics(
            references[construct],
            predictions[construct],
            clusters[construct],
            ["present"],
            gates.gates[construct],
            args.bootstrap_seed + index,
            maximum_absolute_error=maximum_errors[construct],
            invalid_output_count=invalid_counts[construct],
        )
    report = build_scoring_validation_report(
        diagnostics,
        len(sample.conversation_ids),
        gates.manifest_sha256,
        sample.manifest_sha256,
        datetime.now(timezone.utc),
    )
    write_model_json_atomic(args.output, report)
    print(f"Wrote six-construct blinded validation report to {args.output}")


if __name__ == "__main__":
    main()
