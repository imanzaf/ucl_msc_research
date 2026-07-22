"""Derive hard scoring gates from blinded human and automated judgments."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from src.data_models.annotations import ConversationAnnotation
from src.data_models.common import artifact_sha256, file_sha256, validate_model_self_hash
from src.data_models.manifests import AnnotationSampleManifest
from src.data_models.scenario_review import ReviewPass
from src.data_models.scoring import (
    ClaimAssessmentJudgment,
    CommunicationState,
    DisclosureState,
    FactAssessmentJudgment,
    FailedConstructActionInput,
    FramingState,
    ScoredConversationBundle,
)
from src.review_app import build_repeat_scoring_input
from src.scoring.annotation_resolution import final_annotations
from src.scoring.reliability import binary_recall, build_scoring_validation_report, claim_level_precision_recall, weighted_kappa
from src.storage import read_model_json, read_model_jsonl, write_model_json_atomic


def _judgment_map(annotation: ConversationAnnotation) -> Dict[Tuple[str, str], FactAssessmentJudgment]:
    """Index human fact judgments by fact and checkpoint."""
    return {(item.fact_id, item.checkpoint.value): item for item in annotation.fact_judgments}


def main() -> None:
    """Validate sample provenance, calculate agreement/error gates, and persist dispositions."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotation-sample-manifest", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--scored-bundles", type=Path, required=True)
    parser.add_argument("--source-transcripts", type=Path, required=True)
    parser.add_argument("--failed-actions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--framing-used-in-headline", action="store_true")
    parser.add_argument("--reassurance-used-in-headline", action="store_true")
    args = parser.parse_args()
    sample = read_model_json(args.annotation_sample_manifest, AnnotationSampleManifest)
    validate_model_self_hash(sample, "manifest_sha256")
    if sample.source_transcripts_sha256 != file_sha256(args.source_transcripts):
        raise ValueError("annotation sample does not bind the supplied transcript bytes")
    annotations = read_model_jsonl(args.annotations, ConversationAnnotation)
    resolved_annotations, repeat_pairs = final_annotations(sample, annotations)
    bundle_by_blind = {
        bundle.scoring_input.blind_conversation_id: bundle
        for bundle in read_model_jsonl(args.scored_bundles, ScoredConversationBundle)
        if bundle.scoring_input.blind_conversation_id in set(sample.conversation_ids)
    }
    if set(bundle_by_blind) != set(sample.conversation_ids):
        raise ValueError("automated scoring bundles must cover the complete frozen annotation sample")
    for blind_id, annotation in resolved_annotations.items():
        bundle = bundle_by_blind[blind_id]
        if annotation.annotation_pass == ReviewPass.INITIAL:
            if annotation.scoring_input_sha256 != artifact_sha256(bundle.scoring_input):
                raise ValueError("human annotation and automated bundle use different blind inputs")
        else:
            initial = next(
                item for item in annotations if item.annotation_id == annotation.initial_annotation_id and item.annotation_pass == ReviewPass.INITIAL
            )
            expected_repeat = build_repeat_scoring_input(bundle.scoring_input, initial.annotation_id)
            if annotation.blind_conversation_id != expected_repeat.blind_conversation_id:
                raise ValueError("repeat annotation does not bind the deterministic reshuffled blind item")
            if annotation.scoring_input_sha256 != artifact_sha256(expected_repeat):
                raise ValueError("repeat annotation does not bind the exact reshuffled scoring input")

    disclosure_credit = {DisclosureState.OMITTED: 0, DisclosureState.PARTIAL: 1, DisclosureState.FULL: 2}
    intra_first: List[int] = []
    intra_second: List[int] = []
    for initial, repeat in repeat_pairs:
        first = _judgment_map(initial)
        second = _judgment_map(repeat)
        for key in sorted(first):
            intra_first.append(disclosure_credit[first[key].disclosure])
            intra_second.append(disclosure_credit[second[key].disclosure])

    reference_disclosure: List[int] = []
    judge_disclosure: List[int] = []
    reference_omission: List[int] = []
    judge_omission: List[int] = []
    reference_framing: List[int] = []
    judge_framing: List[int] = []
    reference_reassurance: List[int] = []
    judge_reassurance: List[int] = []
    framing_credit = {
        FramingState.PROPORTIONATE: 0,
        FramingState.MINIMISED: 1,
        FramingState.EXAGGERATED: 2,
        FramingState.NOT_APPLICABLE: 3,
    }
    reference_claims: List[Tuple[str, ClaimAssessmentJudgment]] = []
    predicted_claims: List[Tuple[str, ClaimAssessmentJudgment]] = []
    for blind_id in sample.conversation_ids:
        human = resolved_annotations[blind_id]
        bundle = bundle_by_blind[blind_id]
        human_facts = _judgment_map(human)
        judge_facts = {(item.fact_id, item.checkpoint.value): item for item in bundle.fact_result.judgments}
        if set(human_facts) != set(judge_facts):
            raise ValueError("human and judge fact/checkpoint keys differ")
        for key in sorted(human_facts):
            reference = human_facts[key]
            judged = judge_facts[key]
            reference_disclosure.append(disclosure_credit[reference.disclosure])
            judge_disclosure.append(disclosure_credit[judged.disclosure])
            reference_omission.append(int(reference.disclosure == DisclosureState.OMITTED))
            judge_omission.append(int(judged.disclosure == DisclosureState.OMITTED))
            if key[0].rsplit("_", 1)[-1].startswith("F") and reference.disclosure != DisclosureState.OMITTED:
                reference_framing.append(framing_credit[reference.framing])
                judge_framing.append(framing_credit[judged.framing])
        human_responses = {item.checkpoint: item for item in human.response_judgments}
        judge_responses = {item.checkpoint: item for item in bundle.response_result.judgments}
        for checkpoint in sorted(human_responses, key=lambda item: item.value):
            reference_reassurance.append(int(human_responses[checkpoint].unsupported_reassurance == CommunicationState.PRESENT))
            judge_reassurance.append(int(judge_responses[checkpoint].unsupported_reassurance == CommunicationState.PRESENT))
        reference_claims.extend((blind_id, claim) for claim in human.claim_judgments)
        predicted_claims.extend((blind_id, claim) for claim in bundle.claim_result.claims)
    false_claim_precision, false_claim_recall = claim_level_precision_recall(reference_claims, predicted_claims)
    failed_actions = read_model_json(args.failed_actions, FailedConstructActionInput).actions
    report = build_scoring_validation_report(
        intra_rater_disclosure_weighted_kappa=weighted_kappa(intra_first, intra_second),
        judge_reference_disclosure_weighted_kappa=weighted_kappa(reference_disclosure, judge_disclosure),
        omission_recall=binary_recall(reference_omission, judge_omission),
        false_claim_precision=false_claim_precision,
        false_claim_recall=false_claim_recall,
        framing_kappa=weighted_kappa(reference_framing, judge_framing),
        reassurance_kappa=weighted_kappa(reference_reassurance, judge_reassurance),
        framing_used_in_headline=args.framing_used_in_headline,
        reassurance_used_in_headline=args.reassurance_used_in_headline,
        failed_construct_actions=failed_actions,
        validation_sample_manifest_sha256=sample.manifest_sha256,
        generated_at=datetime.now(timezone.utc),
    )
    write_model_json_atomic(args.output, report)
    print(f"Wrote scoring validation report with {len(report.failed_constructs)} failed constructs to {args.output}")


if __name__ == "__main__":
    main()
