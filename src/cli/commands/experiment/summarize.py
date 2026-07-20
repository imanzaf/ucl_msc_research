"""Generate self-hashed per-model terminal and token summaries for risk_comm_v1."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from src.data_models.common import artifact_sha256
from src.data_models.experiments import EXPECTED_CONVERSATION_COUNT, ConversationTranscript, ModelSummary, RunOutcomeStatus
from src.experiments.scenario_runner import validate_complete_run_plan
from src.storage import read_model_jsonl, write_models_jsonl_atomic


def main() -> None:
    """Validate the full design and atomically write three model summaries."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcripts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    transcripts = read_model_jsonl(args.transcripts, ConversationTranscript)
    validate_complete_run_plan([transcript.run_unit for transcript in transcripts])
    model_ids = sorted({transcript.run_unit.model_id for transcript in transcripts})
    if not model_ids or EXPECTED_CONVERSATION_COUNT % len(model_ids) != 0:
        raise ValueError("expected conversation count must divide evenly across evaluated models")
    expected_conversations_per_model = EXPECTED_CONVERSATION_COUNT // len(model_ids)
    summaries = []
    for model_id in model_ids:
        records = [transcript for transcript in transcripts if transcript.run_unit.model_id == model_id]
        returned_versions: Counter[str] = Counter()
        input_tokens = 0
        output_tokens = 0
        for transcript in records:
            for attempt in [*transcript.initial_attempts, *transcript.follow_up_attempts]:
                if attempt.usage is not None:
                    input_tokens += attempt.usage.input_tokens
                    output_tokens += attempt.usage.output_tokens
                if attempt.response_text is not None and attempt.returned_model_version is not None:
                    returned_versions[attempt.returned_model_version] += 1
        payload = {
            "schema_version": "1.0.0",
            "model_id": model_id,
            "expected_conversations": expected_conversations_per_model,
            "completed_conversations": sum(item.outcome_status == RunOutcomeStatus.COMPLETED for item in records),
            "failed_conversations": sum(item.outcome_status == RunOutcomeStatus.FAILED for item in records),
            "missing_conversations": sum(item.outcome_status == RunOutcomeStatus.MISSING for item in records),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "returned_model_versions": dict(returned_versions),
        }
        summaries.append(ModelSummary.model_validate({**payload, "summary_sha256": artifact_sha256(payload)}))
    if len(summaries) != 3:
        raise ValueError("risk_comm_v1 requires exactly three per-model summaries")
    write_models_jsonl_atomic(args.output, summaries)
    print(f"Wrote three self-hashed model summaries to {args.output}")


if __name__ == "__main__":
    main()
