"""Validate and index the one-pass blinded annotation set."""

from __future__ import annotations

from typing import Dict, List

from src.data_models.annotations import ConversationAnnotation
from src.data_models.manifests import AnnotationSampleManifest


def final_annotations(
    sample: AnnotationSampleManifest,
    annotations: List[ConversationAnnotation],
) -> Dict[str, ConversationAnnotation]:
    """Require exactly one frozen-rubric annotation for every sampled conversation."""
    annotation_by_blind: Dict[str, ConversationAnnotation] = {}
    by_id = {annotation.annotation_id: annotation for annotation in annotations}
    if len(by_id) != len(annotations):
        raise ValueError("annotation file contains duplicate annotation identifiers")
    for annotation in annotations:
        if annotation.blind_conversation_id in annotation_by_blind:
            raise ValueError("sample conversation has more than one annotation")
        annotation_by_blind[annotation.blind_conversation_id] = annotation
    if set(annotation_by_blind) != set(sample.conversation_ids):
        raise ValueError("annotations must cover exactly the frozen annotation sample")
    if len({annotation.rubric_sha256 for annotation in annotations}) != 1:
        raise ValueError("all locked annotations must use one exact frozen rubric")
    return annotation_by_blind
