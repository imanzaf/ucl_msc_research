"""Resolve blinded initial, repeat, and resolution annotation records."""

from __future__ import annotations

from typing import Dict, List, Tuple

from src.data_models.annotations import ConversationAnnotation
from src.data_models.manifests import AnnotationSampleManifest
from src.data_models.scenario_review import ReviewPass


def final_annotations(
    sample: AnnotationSampleManifest,
    annotations: List[ConversationAnnotation],
) -> Tuple[Dict[str, ConversationAnnotation], List[Tuple[ConversationAnnotation, ConversationAnnotation]]]:
    """Resolve the locked first/repeat/resolution workflow without treatment access."""
    initial_by_blind: Dict[str, ConversationAnnotation] = {}
    by_id = {annotation.annotation_id: annotation for annotation in annotations}
    if len(by_id) != len(annotations):
        raise ValueError("annotation file contains duplicate annotation identifiers")
    for annotation in annotations:
        if annotation.annotation_pass == ReviewPass.INITIAL:
            if annotation.blind_conversation_id in initial_by_blind:
                raise ValueError("sample conversation has more than one initial annotation")
            initial_by_blind[annotation.blind_conversation_id] = annotation
    if set(initial_by_blind) != set(sample.conversation_ids):
        raise ValueError("initial annotations must cover exactly the frozen annotation sample")
    repeats: Dict[str, ConversationAnnotation] = {}
    resolutions: Dict[Tuple[str, str], ConversationAnnotation] = {}
    for annotation in annotations:
        if annotation.annotation_pass == ReviewPass.REPEAT:
            initial = by_id.get(annotation.initial_annotation_id or "")
            if initial is None or initial.annotation_pass != ReviewPass.INITIAL:
                raise ValueError("repeat annotation does not bind a valid initial annotation")
            repeats[initial.blind_conversation_id] = annotation
        elif annotation.annotation_pass == ReviewPass.RESOLUTION:
            resolutions[(annotation.initial_annotation_id or "", annotation.repeat_annotation_id or "")] = annotation
    if set(repeats) != set(sample.repeat_conversation_ids):
        raise ValueError("repeat annotations must cover exactly the frozen repeat sample")
    final = dict(initial_by_blind)
    pairs: List[Tuple[ConversationAnnotation, ConversationAnnotation]] = []
    for blind_id, repeat in repeats.items():
        initial = initial_by_blind[blind_id]
        pairs.append((initial, repeat))
        disagreement = (
            initial.fact_judgments != repeat.fact_judgments
            or initial.response_judgments != repeat.response_judgments
            or initial.claim_judgments != repeat.claim_judgments
        )
        resolution = resolutions.get((initial.annotation_id, repeat.annotation_id))
        if disagreement and resolution is None:
            raise ValueError("every repeated annotation disagreement requires a resolution")
        if not disagreement and resolution is not None:
            raise ValueError("agreement cannot have a resolution annotation")
        final[blind_id] = resolution or repeat
    if len({annotation.rubric_sha256 for annotation in annotations}) != 1:
        raise ValueError("all locked annotations must use one exact frozen rubric")
    return final, pairs
