"""Researcher-approved, provenance-preserving curation of generated scenarios."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import Field, model_validator

from src.common import ImmutableModel, artifact_sha256, utc_now
from src.models.scenarios import AcceptedScenario
from src.models.seeds import ScenarioSeedSet
from src.scenarios.execution import generation_request_batch_sha256
from src.scenarios.generation import GeneratedScenarioOutput, GenerationRequest, assemble_pending_scenario


class FactTextCuration(ImmutableModel):
    """Bind one approved fact-text replacement to its exact original text."""

    fact_id: str = Field(pattern=r"^[A-Z0-9_]+_F[1-6]$")
    original_text: str
    revised_text: str
    reason: str


class ContextCuration(ImmutableModel):
    """Bind one approved decision-context replacement to its original text."""

    scenario_id: str = Field(pattern=r"^[A-Z]{2,3}[0-9]{3}_R[1-5]$")
    original_context: str
    revised_context: str
    reason: str


class BriefCuration(ImmutableModel):
    """Bind one approved seed-brief correction to its original wording."""

    fact_id: str = Field(pattern=r"^[A-Z0-9_]+_F[1-6]$")
    original_brief: str
    revised_brief: str
    reason: str


class AnchorCuration(ImmutableModel):
    """Bind one approved specificity-anchor replacement to its original value."""

    fact_id: str = Field(pattern=r"^[A-Z0-9_]+_F[1-6]$")
    original_anchor: str
    revised_anchor: str
    reason: str


class CorpusCurationApproval(ImmutableModel):
    """Bind researcher approval to exact source artifacts and every correction."""

    schema_version: str = Field(default="4.0.0", pattern=r"^4\.0\.0$")
    source_generation_request_batch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_seed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_generated_outputs_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manual_review_audit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_text_edits: List[FactTextCuration]
    context_edits: List[ContextCuration]
    brief_edits: List[BriefCuration]
    anchor_edits: List[AnchorCuration]
    approved_by: str = Field(min_length=2)
    approved_at: datetime
    approval_note: str = Field(min_length=2)
    curation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_curation(self) -> "CorpusCurationApproval":
        """Require unique edits and bind the canonical curation hash."""
        identifiers = [edit.fact_id for edit in self.fact_text_edits]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("fact-text curation identifiers must be unique")
        for edits in (self.brief_edits, self.anchor_edits):
            edit_ids = [edit.fact_id for edit in edits]
            if len(edit_ids) != len(set(edit_ids)):
                raise ValueError("seed curation identifiers must be unique within each edit type")
        context_ids = [edit.scenario_id for edit in self.context_edits]
        if len(context_ids) != len(set(context_ids)):
            raise ValueError("context curation scenario identifiers must be unique")
        expected_hash = artifact_sha256(self.model_dump(mode="json", exclude={"curation_sha256"}))
        if self.curation_sha256 != expected_hash:
            raise ValueError("corpus-curation hash does not match canonical content")
        return self


def source_generated_outputs_sha256(outputs: List[GeneratedScenarioOutput]) -> str:
    """Hash an ordered generated-output corpus for curation binding."""
    if len(outputs) != 30 or len({output.scenario_id for output in outputs}) != 30:
        raise ValueError("corpus curation requires thirty unique generated outputs")
    return artifact_sha256([output.model_dump(mode="json") for output in outputs])


def build_curation_approval(
    seed_set: ScenarioSeedSet,
    outputs: List[GeneratedScenarioOutput],
    generation_requests: List[GenerationRequest],
    manual_review_audit: Dict[str, object],
    approved_by: str,
    approval_note: str,
    approved_at: Optional[datetime] = None,
) -> CorpusCurationApproval:
    """Build the exact correction set documented in an approved manual-review audit."""
    output_facts = {fact.fact_id: fact for output in outputs for fact in output.facts}
    seed_facts: Dict[str, tuple[str, str]] = {}
    scenario_contexts: Dict[str, str] = {}
    for use_case in seed_set.use_cases:
        for scenario in use_case.replications:
            scenario_contexts[scenario.scenario_id] = scenario.decision_context
            fact_number = 1
            for pair in scenario.fact_pair_briefs:
                for brief in (pair.owner_supporting_fact, pair.countervailing_fact):
                    seed_facts[f"{scenario.scenario_id}_F{fact_number}"] = (brief.brief, brief.required_specificity)
                    fact_number += 1
    raw_findings = manual_review_audit.get("revision_findings")
    if not isinstance(raw_findings, list):
        raise ValueError("manual review audit does not contain revision findings")
    fact_edits: List[FactTextCuration] = []
    context_edits: List[ContextCuration] = []
    brief_edits: List[BriefCuration] = []
    anchor_edits: List[AnchorCuration] = []
    for raw_finding in raw_findings:
        if not isinstance(raw_finding, dict):
            raise ValueError("manual review finding must be an object")
        scenario_id = str(raw_finding["scenario_id"])
        reason = str(raw_finding["reason"])
        proposed_text = raw_finding.get("proposed_fact_text", {})
        if not isinstance(proposed_text, dict):
            raise ValueError(f"proposed fact text must be an object for {scenario_id}")
        for fact_id, revised_text in proposed_text.items():
            source = output_facts.get(str(fact_id))
            if source is None:
                raise ValueError(f"manual review references unknown generated fact {fact_id}")
            fact_edits.append(FactTextCuration(fact_id=str(fact_id), original_text=source.text, revised_text=str(revised_text), reason=reason))
        context_addition = raw_finding.get("proposed_context_addition")
        if context_addition is not None:
            original = scenario_contexts[scenario_id]
            context_edits.append(
                ContextCuration(
                    scenario_id=scenario_id,
                    original_context=original,
                    revised_context=f"{original} {context_addition}",
                    reason=reason,
                )
            )
        singular_brief = raw_finding.get("proposed_brief_revision")
        if isinstance(singular_brief, dict):
            fact_id = str(singular_brief["fact_id"])
            brief_edits.append(
                BriefCuration(
                    fact_id=fact_id,
                    original_brief=seed_facts[fact_id][0],
                    revised_brief=str(singular_brief["revised_brief"]),
                    reason=reason,
                )
            )
        plural_briefs = raw_finding.get("proposed_brief_revisions", {})
        if not isinstance(plural_briefs, dict):
            raise ValueError(f"proposed brief revisions must be an object for {scenario_id}")
        for fact_id, revised_brief in plural_briefs.items():
            brief_edits.append(
                BriefCuration(
                    fact_id=str(fact_id),
                    original_brief=seed_facts[str(fact_id)][0],
                    revised_brief=str(revised_brief),
                    reason=reason,
                )
            )
        proposed_anchors = raw_finding.get("proposed_anchor_revision", {})
        if not isinstance(proposed_anchors, dict):
            raise ValueError(f"proposed anchor revisions must be an object for {scenario_id}")
        for fact_id, revised_anchor in proposed_anchors.items():
            anchor_edits.append(
                AnchorCuration(
                    fact_id=str(fact_id),
                    original_anchor=seed_facts[str(fact_id)][1],
                    revised_anchor=str(revised_anchor),
                    reason=reason,
                )
            )
    expected_fact_count = manual_review_audit.get("summary", {})
    if not isinstance(expected_fact_count, dict) or len(fact_edits) != int(expected_fact_count["additional_fact_text_revisions_proposed"]):
        raise ValueError("manual review fact-edit count does not match its summary")
    base = {
        "schema_version": "4.0.0",
        "source_generation_request_batch_sha256": generation_request_batch_sha256(generation_requests),
        "source_seed_sha256": artifact_sha256(seed_set),
        "source_generated_outputs_sha256": source_generated_outputs_sha256(outputs),
        "manual_review_audit_sha256": artifact_sha256(manual_review_audit),
        "fact_text_edits": fact_edits,
        "context_edits": context_edits,
        "brief_edits": brief_edits,
        "anchor_edits": anchor_edits,
        "approved_by": approved_by,
        "approved_at": approved_at or utc_now(),
        "approval_note": approval_note,
    }
    return CorpusCurationApproval.model_validate({**base, "curation_sha256": artifact_sha256(base)})


def curate_seed_set(seed_set: ScenarioSeedSet, approval: CorpusCurationApproval) -> ScenarioSeedSet:
    """Apply only approved context, brief, and anchor edits to a copied seed set."""
    if artifact_sha256(seed_set) != approval.source_seed_sha256:
        raise ValueError("curation approval belongs to a different source seed set")
    payload = seed_set.model_dump(mode="json")
    contexts = {edit.scenario_id: edit for edit in approval.context_edits}
    briefs = {edit.fact_id: edit for edit in approval.brief_edits}
    anchors = {edit.fact_id: edit for edit in approval.anchor_edits}
    seen_contexts: set[str] = set()
    seen_briefs: set[str] = set()
    seen_anchors: set[str] = set()
    for use_case in payload["use_cases"]:
        for scenario in use_case["replications"]:
            scenario_id = str(scenario["scenario_id"])
            if scenario_id in contexts:
                context_edit = contexts[scenario_id]
                if scenario["decision_context"] != context_edit.original_context:
                    raise ValueError(f"source decision context changed before curation for {scenario_id}")
                scenario["decision_context"] = context_edit.revised_context
                seen_contexts.add(scenario_id)
            fact_number = 1
            for pair in scenario["fact_pair_briefs"]:
                for direction_key in ("owner_supporting_fact", "countervailing_fact"):
                    fact_id = f"{scenario_id}_F{fact_number}"
                    fact = pair[direction_key]
                    if fact_id in briefs:
                        brief_edit = briefs[fact_id]
                        if fact["brief"] != brief_edit.original_brief:
                            raise ValueError(f"source brief changed before curation for {fact_id}")
                        fact["brief"] = brief_edit.revised_brief
                        seen_briefs.add(fact_id)
                    if fact_id in anchors:
                        anchor_edit = anchors[fact_id]
                        if fact["required_specificity"] != anchor_edit.original_anchor:
                            raise ValueError(f"source anchor changed before curation for {fact_id}")
                        fact["required_specificity"] = anchor_edit.revised_anchor
                        seen_anchors.add(fact_id)
                    fact_number += 1
    if seen_contexts != set(contexts) or seen_briefs != set(briefs) or seen_anchors != set(anchors):
        raise ValueError("one or more approved seed edits did not match a source scenario fact")
    return ScenarioSeedSet.model_validate(payload)


def curate_generated_outputs(outputs: List[GeneratedScenarioOutput], approval: CorpusCurationApproval) -> List[GeneratedScenarioOutput]:
    """Apply only approved fact-text and anchor edits to copied generated outputs."""
    if source_generated_outputs_sha256(outputs) != approval.source_generated_outputs_sha256:
        raise ValueError("curation approval belongs to different generated outputs")
    text_edits = {edit.fact_id: edit for edit in approval.fact_text_edits}
    anchor_edits = {edit.fact_id: edit for edit in approval.anchor_edits}
    seen_text: set[str] = set()
    seen_anchor: set[str] = set()
    curated: List[GeneratedScenarioOutput] = []
    for output in outputs:
        payload = output.model_dump(mode="json")
        for fact in payload["facts"]:
            fact_id = str(fact["fact_id"])
            if fact_id in text_edits:
                text_edit = text_edits[fact_id]
                if fact["text"] != text_edit.original_text:
                    raise ValueError(f"source fact text changed before curation for {fact_id}")
                fact["text"] = text_edit.revised_text
                seen_text.add(fact_id)
            if fact_id in anchor_edits:
                anchor_edit = anchor_edits[fact_id]
                if fact["anchor"] != anchor_edit.original_anchor:
                    raise ValueError(f"source fact anchor changed before curation for {fact_id}")
                fact["anchor"] = anchor_edit.revised_anchor
                seen_anchor.add(fact_id)
        curated.append(GeneratedScenarioOutput.model_validate(payload))
    if seen_text != set(text_edits) or seen_anchor != set(anchor_edits):
        raise ValueError("one or more approved generated-output edits did not match a source fact")
    return curated


def assemble_curated_pending_corpus(
    source_seed_set: ScenarioSeedSet,
    source_outputs: List[GeneratedScenarioOutput],
    generation_requests: List[GenerationRequest],
    approval: CorpusCurationApproval,
) -> tuple[ScenarioSeedSet, List[GeneratedScenarioOutput], List[AcceptedScenario]]:
    """Curate and assemble while retaining each original generation-request hash."""
    if generation_request_batch_sha256(generation_requests) != approval.source_generation_request_batch_sha256:
        raise ValueError("curation approval belongs to a different generation-request batch")
    curated_seed_set = curate_seed_set(source_seed_set, approval)
    curated_outputs = curate_generated_outputs(source_outputs, approval)
    by_output = {output.scenario_id: output for output in curated_outputs}
    request_hashes = {request.scenario_id: request.request_sha256 for request in generation_requests}
    scenarios = [
        assemble_pending_scenario(
            seed,
            use_case.use_case_name,
            by_output[seed.scenario_id],
            use_case.deployment_context,
            generation_request_sha256=request_hashes[seed.scenario_id],
        )
        for use_case in curated_seed_set.use_cases
        for seed in use_case.replications
    ]
    return curated_seed_set, curated_outputs, scenarios
