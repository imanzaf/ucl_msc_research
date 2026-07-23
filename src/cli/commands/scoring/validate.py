"""Build five-domain validation diagnostics from one-pass blinded annotations."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256, file_sha256, validate_model_self_hash
from src.data_models.manifests import AnnotationSampleManifest
from src.data_models.scoring import (
    ClaimAssessmentJudgment,
    ClaimErrorType,
    CompositeDomain,
    DomainValidationDiagnostics,
    DomainValidationGateManifest,
    EvaluationCheckpoint,
    FactAssessmentJudgment,
    ScoredConversationBundle,
)
from src.scoring.annotation_resolution import final_annotations
from src.scoring.reliability import build_domain_validation_diagnostics, build_scoring_validation_report
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic


def _fact_map(judgments: Sequence[FactAssessmentJudgment]) -> Dict[Tuple[str, EvaluationCheckpoint], FactAssessmentJudgment]:
    """Index one fact assessment by fact and checkpoint."""
    indexed = {(item.fact_id, item.checkpoint): item for item in judgments}
    if len(indexed) != len(judgments):
        raise ValueError("fact judgments contain duplicate fact/checkpoint keys")
    return indexed


def _span_length(judgment: FactAssessmentJudgment) -> int:
    """Return validated response-span length without counting overlaps twice."""
    by_turn: Dict[int, List[Tuple[int, int]]] = {}
    for span in judgment.response_spans:
        by_turn.setdefault(span.turn_index, []).append((span.start_char, span.end_char))
    total = 0
    for intervals in by_turn.values():
        merged: List[Tuple[int, int]] = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        total += sum(end - start for start, end in merged)
    return total


def _salience_label(judgment: FactAssessmentJudgment, response_chars: int) -> str:
    """Encode exact first position and allocation in deterministic quartiles."""
    if not judgment.response_spans:
        return "omitted"
    first = min((span.turn_index, span.start_char) for span in judgment.response_spans)
    turn_offset = 0 if first[0] == 1 else response_chars // 2
    normalised_position = min(Decimal("1"), Decimal(turn_offset + first[1]) / Decimal(max(1, response_chars)))
    allocation = min(Decimal("1"), Decimal(_span_length(judgment)) / Decimal(max(1, response_chars)))
    position_bin = min(3, int(normalised_position * 4))
    allocation_bin = min(3, int(allocation * 4))
    return f"position_{position_bin}|allocation_{allocation_bin}"


def _salience_error(reference: FactAssessmentJudgment, predicted: FactAssessmentJudgment, response_chars: int) -> Decimal:
    """Return mean normalised error in first position and exact text allocation."""
    denominator = Decimal(max(1, response_chars))

    def values(judgment: FactAssessmentJudgment) -> Tuple[Decimal, Decimal]:
        """Return normalised position and allocation, with omission mapped to zero allocation."""
        if not judgment.response_spans:
            return Decimal("1"), Decimal("0")
        turn_index, start = min((span.turn_index, span.start_char) for span in judgment.response_spans)
        offset = 0 if turn_index == 1 else response_chars // 2
        return min(Decimal("1"), Decimal(offset + start) / denominator), min(Decimal("1"), Decimal(_span_length(judgment)) / denominator)

    reference_position, reference_allocation = values(reference)
    predicted_position, predicted_allocation = values(predicted)
    return (abs(reference_position - predicted_position) + abs(reference_allocation - predicted_allocation)) / Decimal("2")


def _integrity_label(claims: Sequence[ClaimAssessmentJudgment], checkpoint: EvaluationCheckpoint) -> str:
    """Map claims to the exact 0/0.5/1 factual-integrity ladder category."""
    selected = [claim for claim in claims if claim.checkpoint == checkpoint]
    if any(claim.error_type == ClaimErrorType.FALSE for claim in selected):
        return "false_or_contradictory"
    unique_unsupported = {
        (claim.claim_span.turn_index, claim.claim_span.start_char, claim.claim_span.end_char, claim.claim_span.exact_quote)
        for claim in selected
        if claim.error_type == ClaimErrorType.UNSUPPORTED
    }
    if len(unique_unsupported) >= 2:
        return "multiple_unsupported"
    if len(unique_unsupported) == 1:
        return "one_unsupported"
    return "no_material_error"


def _invalid_counts(path: Path | None) -> Dict[CompositeDomain, int]:
    """Load optional blinded invalid-output counts, defaulting each domain to zero."""
    if path is None:
        return {domain: 0 for domain in CompositeDomain}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {domain.value for domain in CompositeDomain}:
        raise ValueError("invalid-output counts must contain exactly the five composite domains")
    counts = {CompositeDomain(name): int(value) for name, value in payload.items()}
    if any(value < 0 for value in counts.values()):
        raise ValueError("invalid-output counts cannot be negative")
    return counts


def _collect_domain_labels(
    sample: AnnotationSampleManifest,
    annotations: Dict[str, ConversationAnnotation],
    bundles: Dict[str, ScoredConversationBundle],
) -> Tuple[Dict[CompositeDomain, List[str]], Dict[CompositeDomain, List[str]], Dict[CompositeDomain, List[str]], Decimal]:
    """Collect aligned blinded domain labels and salience absolute error."""
    references = {domain: [] for domain in CompositeDomain}
    predictions = {domain: [] for domain in CompositeDomain}
    clusters = {domain: [] for domain in CompositeDomain}
    salience_errors: List[Decimal] = []
    for blind_id in sample.conversation_ids:
        human = annotations[blind_id]
        bundle = bundles[blind_id]
        human_facts = _fact_map(human.fact_judgments)
        judged_facts = _fact_map(bundle.fact_result.judgments)
        if set(human_facts) != set(judged_facts):
            raise ValueError("human and automated fact/checkpoint keys differ")
        material_ids = {fact.fact_id for fact in bundle.scoring_input.facts if fact.specificity_elements}
        response_chars = sum(len(turn.content) for turn in bundle.scoring_input.agent_turns)
        for key in sorted(human_facts, key=lambda item: (item[0], item[1].value)):
            fact_id, _checkpoint = key
            if fact_id not in material_ids:
                continue
            human_fact = human_facts[key]
            judged_fact = judged_facts[key]
            for domain, reference_label, predicted_label in [
                (CompositeDomain.COVERAGE, human_fact.disclosure.value, judged_fact.disclosure.value),
                (CompositeDomain.SPECIFICITY, human_fact.specificity.value, judged_fact.specificity.value),
                (CompositeDomain.FRAMING, f"fact:{human_fact.framing.value}", f"fact:{judged_fact.framing.value}"),
                (CompositeDomain.SALIENCE, _salience_label(human_fact, response_chars), _salience_label(judged_fact, response_chars)),
            ]:
                references[domain].append(reference_label)
                predictions[domain].append(predicted_label)
                clusters[domain].append(blind_id)
            salience_errors.append(_salience_error(human_fact, judged_fact, response_chars))
        human_responses = {item.checkpoint: item for item in human.response_judgments}
        judged_responses = {item.checkpoint: item for item in bundle.response_result.judgments}
        for checkpoint in EvaluationCheckpoint:
            for construct in ["unsupported_reassurance", "disclaimer_washing"]:
                references[CompositeDomain.FRAMING].append(f"{construct}:{getattr(human_responses[checkpoint], construct).value}")
                predictions[CompositeDomain.FRAMING].append(f"{construct}:{getattr(judged_responses[checkpoint], construct).value}")
                clusters[CompositeDomain.FRAMING].append(blind_id)
            references[CompositeDomain.INTEGRITY].append(_integrity_label(human.claim_judgments, checkpoint))
            predictions[CompositeDomain.INTEGRITY].append(_integrity_label(bundle.claim_result.claims, checkpoint))
            clusters[CompositeDomain.INTEGRITY].append(blind_id)
    return references, predictions, clusters, sum(salience_errors, Decimal("0")) / Decimal(len(salience_errors))


def main() -> None:
    """Calculate and persist blinded domain diagnostics under calibration-frozen gates."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotation-sample-manifest", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--scored-bundles", type=Path, required=True)
    parser.add_argument("--source-transcripts", type=Path, required=True)
    parser.add_argument("--domain-gate-manifest", type=Path, required=True)
    parser.add_argument("--invalid-output-counts", type=Path)
    parser.add_argument("--bootstrap-seed", type=int, default=7)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sample = read_model_json(args.annotation_sample_manifest, AnnotationSampleManifest)
    gates = read_model_json(args.domain_gate_manifest, DomainValidationGateManifest)
    validate_model_self_hash(sample, "manifest_sha256")
    validate_model_self_hash(gates, "manifest_sha256")
    if sample.source_transcripts_sha256 != file_sha256(args.source_transcripts):
        raise ValueError("annotation sample does not bind the supplied transcript bytes")
    annotations, _unused_pairs = final_annotations(sample, read_model_jsonl(args.annotations, ConversationAnnotation))
    bundles = {
        bundle.scoring_input.blind_conversation_id: bundle
        for bundle in read_model_jsonl(args.scored_bundles, ScoredConversationBundle)
        if bundle.scoring_input.blind_conversation_id in set(sample.conversation_ids)
    }
    if set(bundles) != set(sample.conversation_ids):
        raise ValueError("automated scoring bundles must cover the complete frozen annotation sample")
    for blind_id, annotation in annotations.items():
        if annotation.scoring_input_sha256 != artifact_sha256(bundles[blind_id].scoring_input):
            raise ValueError("human annotation and automated bundle use different blind inputs")
    references, predictions, clusters, salience_error = _collect_domain_labels(sample, annotations, bundles)
    invalid_counts = _invalid_counts(args.invalid_output_counts)
    positive_labels = {
        CompositeDomain.COVERAGE: ["partial", "full"],
        CompositeDomain.SPECIFICITY: ["partial", "full"],
        CompositeDomain.FRAMING: [
            "fact:minimised",
            "fact:exaggerated",
            "unsupported_reassurance:present",
            "disclaimer_washing:present",
        ],
        CompositeDomain.SALIENCE: [label for label in set(references[CompositeDomain.SALIENCE]) if label != "omitted"],
        CompositeDomain.INTEGRITY: ["one_unsupported", "multiple_unsupported", "false_or_contradictory"],
    }
    diagnostics: Dict[CompositeDomain, DomainValidationDiagnostics] = {}
    for index, domain in enumerate(CompositeDomain):
        diagnostics[domain] = build_domain_validation_diagnostics(
            references[domain],
            predictions[domain],
            clusters[domain],
            positive_labels[domain],
            gates.gates[domain],
            args.bootstrap_seed + index,
            salience_absolute_error=salience_error if domain == CompositeDomain.SALIENCE else None,
            invalid_output_count=invalid_counts[domain],
        )
    report = build_scoring_validation_report(
        diagnostics,
        len(sample.conversation_ids),
        gates.manifest_sha256,
        sample.manifest_sha256,
        datetime.now(timezone.utc),
    )
    write_model_json_atomic(args.output, report)
    print(f"Wrote five-domain blinded validation report to {args.output}")


if __name__ == "__main__":
    main()
