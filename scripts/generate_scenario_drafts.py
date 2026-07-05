"""Generate human-reviewable scenario-family drafts with Pydantic structured output."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from loguru import logger
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from configs.api_settings import get_api_settings  # noqa: E402
from configs.model_settings import get_model_settings  # noqa: E402
from src.data_models.scenarios import (  # noqa: E402
    GeneratedScenarioInstance,
    PromptCondition,
    PromptInstructions,
    PromptTemplate,
    PromptVariant,
    ScenarioFamily,
    ScenarioInstance,
    ScenarioSeed,
    ScenarioSeedScenario,
)
from src.prompts.scenarios.scenario_instance_generation import (  # noqa: E402
    GENERATOR_INSTRUCTIONS,
    INTEGRITY_GUIDANCE,
)
from src.prompts.scenarios.scenario_instance_generation import (  # noqa: E402
    build_prompt_task as render_prompt_task,
)
from src.prompts.scenarios.scenario_instance_generation import (  # noqa: E402
    render_scenario_instance_generation_prompt,
)

DEFAULT_SCENARIO_ROOT = Path("data/inputs/scenarios")
DEFAULT_SCENARIO_SET = "v0.1.0"
SEED_FILENAME = "scenario_generation_seeds.json"
RUNS_DIRNAME = "runs"
RUN_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}$")
PROMPT_VARIANT_ORDER = [
    PromptCondition.NEUTRAL,
    PromptCondition.PRODUCTION_BASELINE,
    PromptCondition.PRODUCTION_INTEGRITY,
]


def resolve_scenario_root(scenario_root: Path) -> Path:
    """Resolve the scenario root path relative to the repository root when needed."""
    if scenario_root.is_absolute():
        return scenario_root
    return REPO_ROOT / scenario_root


def resolve_scenario_set_dir(scenario_root: Path, scenario_set: str) -> Path:
    """Return the directory containing seeds and generated drafts for one scenario set."""
    scenario_set_path = Path(scenario_set)
    if scenario_set_path.is_absolute() or len(scenario_set_path.parts) != 1:
        raise ValueError("scenario set must be a single directory name such as v0.1.0")
    if scenario_set_path.parts[0] in {"", ".", ".."}:
        raise ValueError("scenario set must be a safe directory name such as v0.1.0")
    return resolve_scenario_root(scenario_root) / scenario_set_path


def seed_path_for_scenario_set(scenario_root: Path, scenario_set: str) -> Path:
    """Return the seed JSON path for one scenario set."""
    return (
        resolve_scenario_set_dir(scenario_root=scenario_root, scenario_set=scenario_set)
        / SEED_FILENAME
    )


def create_timestamped_run_id() -> str:
    """Create a timestamp identifier for one scenario generation run."""
    return datetime.now().strftime("%Y%m%dT%H%M%S")


def resolve_run_output_dir(scenario_set_dir: Path, run_id: str) -> Path:
    """Return the timestamped output directory for one scenario generation run."""
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run id must use YYYYMMDDTHHMMSS format")
    return scenario_set_dir / RUNS_DIRNAME / run_id


def expected_prompt_variant_ids(seed: ScenarioSeed) -> Dict[PromptCondition, str]:
    """Return deterministic prompt variant ids derived from family id and prompt condition."""
    return {
        condition: f"{seed.scenario_family_id}_{condition.value}"
        for condition in PROMPT_VARIANT_ORDER
    }


def build_prompt_task(seed: ScenarioSeed) -> str:
    """Build the role/task sentence used in generator prompts and review checks."""
    return render_prompt_task(seed)


def build_scenario_instance_generation_prompt(
    seed: ScenarioSeed,
    seed_scenario: ScenarioSeedScenario,
) -> str:
    """Build the prompt for generating one scenario instance."""
    return render_scenario_instance_generation_prompt(seed=seed, seed_scenario=seed_scenario)


def load_scenario_seeds(seed_path: Path) -> List[ScenarioSeed]:
    """Load scenario generation seeds from a JSON file."""
    logger.info("Loading scenario seeds from {}", seed_path)
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    seeds = [ScenarioSeed.model_validate(seed) for seed in payload["seeds"]]
    logger.info("Loaded {} scenario seed(s)", len(seeds))
    return seeds


def request_generated_scenario_instance(
    client: Any,
    seed: ScenarioSeed,
    seed_scenario: ScenarioSeedScenario,
    model_id: str,
) -> GeneratedScenarioInstance:
    """Request one structured scenario instance from the LLM."""
    logger.info(
        "Requesting scenario instance {} for family {}",
        seed_scenario.scenario_id,
        seed.scenario_family_id,
    )
    response = client.responses.parse(
        model=model_id,
        input=build_scenario_instance_generation_prompt(
            seed=seed,
            seed_scenario=seed_scenario,
        ),
        instructions=GENERATOR_INSTRUCTIONS,
        text_format=GeneratedScenarioInstance,
        store=False,
    )
    if response.output_parsed is None:
        raise ValueError("scenario instance generator returned no parsed output")
    return response.output_parsed


def assemble_scenario_instance(
    generated_instance: GeneratedScenarioInstance,
    seed_scenario: ScenarioSeedScenario,
) -> ScenarioInstance:
    """Attach seed-owned scenario id and user goal to one generated instance."""
    data = generated_instance.model_dump()
    data["scenario_id"] = seed_scenario.scenario_id
    data["user_goal"] = seed_scenario.user_goal
    return ScenarioInstance.model_validate(data)


def generate_scenario_instance(
    client: Any,
    seed: ScenarioSeed,
    seed_scenario: ScenarioSeedScenario,
    model_id: str,
    max_generation_retries: int,
) -> ScenarioInstance:
    """Generate and validate one scenario instance with retry on structured-output failures."""
    last_error: Optional[Exception] = None
    max_attempts = max_generation_retries + 1
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(
                "Generating scenario instance {} (attempt {}/{})",
                seed_scenario.scenario_id,
                attempt,
                max_attempts,
            )
            generated_instance = request_generated_scenario_instance(
                client=client,
                seed=seed,
                seed_scenario=seed_scenario,
                model_id=model_id,
            )
            return assemble_scenario_instance(
                generated_instance=generated_instance,
                seed_scenario=seed_scenario,
            )
        except (ValidationError, ValueError) as exc:
            last_error = exc
            logger.warning(
                "Scenario instance {} failed validation on attempt {}/{}: {}",
                seed_scenario.scenario_id,
                attempt,
                max_attempts,
                exc,
            )

    raise RuntimeError(
        f"failed to generate valid scenario instance {seed_scenario.scenario_id}"
    ) from last_error


def assemble_prompt_variant(
    seed: ScenarioSeed,
    condition: PromptCondition,
) -> PromptVariant:
    """Assemble one code-owned prompt variant from seed fields and fixed guidance."""
    guidance_by_condition: Dict[PromptCondition, str] = {
        PromptCondition.NEUTRAL: "",
        PromptCondition.PRODUCTION_BASELINE: seed.task_guidance,
        PromptCondition.PRODUCTION_INTEGRITY: f"{seed.task_guidance}\n\n{INTEGRITY_GUIDANCE}",
    }
    return PromptVariant(
        prompt_variant_id=expected_prompt_variant_ids(seed)[condition],
        condition=condition,
        system_prompt=PromptInstructions(
            agent_role=seed.agent_role,
            agent_task=seed.agent_task,
            guidance=guidance_by_condition[condition],
        ),
    )


def validate_seed_match(family: ScenarioFamily, seed: ScenarioSeed) -> None:
    """Reject assembled output that changes hardcoded seed constraints."""
    if family.schema_version != "scenario_family.v4":
        raise ValueError("generated schema_version does not match scenario_family.v4")
    if family.scenario_family_id != seed.scenario_family_id:
        raise ValueError("generated scenario_family_id does not match seed")
    if family.segment != seed.segment:
        raise ValueError("generated segment does not match seed")
    if family.interaction_mode != seed.interaction_mode:
        raise ValueError("generated interaction_mode does not match seed")
    if family.tool_using != seed.tool_using:
        raise ValueError("generated tool_using does not match seed")
    if family.agent_role != seed.agent_role:
        raise ValueError("generated agent_role does not match seed")
    if family.agent_task != seed.agent_task:
        raise ValueError("generated agent_task does not match seed")
    if family.task_guidance != seed.task_guidance:
        raise ValueError("generated task_guidance does not match seed")
    if family.user_role != seed.user_role:
        raise ValueError("generated user_role does not match seed")
    expected_instance_goals = {
        seed_scenario.scenario_id: seed_scenario.user_goal for seed_scenario in seed.scenarios
    }
    actual_instance_goals = {
        instance.scenario_id: instance.user_goal for instance in family.scenario_instances
    }
    if actual_instance_goals != expected_instance_goals:
        raise ValueError("generated scenario instance ids or user goals do not match seed")


def attach_seed_metadata(
    scenario_instances: List[ScenarioInstance],
    seed: ScenarioSeed,
) -> ScenarioFamily:
    """Attach seed-owned family metadata and code-owned prompt variants."""
    family = ScenarioFamily(
        schema_version="scenario_family.v4",
        scenario_family_id=seed.scenario_family_id,
        segment=seed.segment,
        interaction_mode=seed.interaction_mode,
        tool_using=seed.tool_using,
        agent_role=seed.agent_role,
        agent_task=seed.agent_task,
        task_guidance=seed.task_guidance,
        user_role=seed.user_role,
        scenario_instances=scenario_instances,
        prompt_variants=[
            assemble_prompt_variant(seed=seed, condition=condition)
            for condition in PROMPT_VARIANT_ORDER
        ],
        prompt_template=PromptTemplate(),
    )
    validate_seed_match(family=family, seed=seed)
    return family


def generate_scenario(
    client: Any,
    seed: ScenarioSeed,
    model_id: str,
    max_generation_retries: int,
) -> ScenarioFamily:
    """Generate and validate one V4 scenario family with five scenario instances."""
    scenario_instances = [
        generate_scenario_instance(
            client=client,
            seed=seed,
            seed_scenario=seed_scenario,
            model_id=model_id,
            max_generation_retries=max_generation_retries,
        )
        for seed_scenario in seed.scenarios
    ]
    family = attach_seed_metadata(scenario_instances=scenario_instances, seed=seed)
    logger.success("Validated family {}", seed.scenario_family_id)
    return family


def render_prompt_variant_review(family: ScenarioFamily) -> str:
    """Render the prompt-variant section of the review report."""
    return "\n".join(
        (
            f"- `{variant.prompt_variant_id}` ({variant.condition.value})\n"
            f"  - Role: {variant.system_prompt.agent_role}\n"
            f"  - Task: {variant.system_prompt.agent_task}\n"
            f"  - Guidance: {variant.system_prompt.guidance or '[none]'}"
        )
        for variant in family.prompt_variants
    )


def render_fact_unit_review(instance: ScenarioInstance) -> str:
    """Render fact units for one generated scenario instance."""
    return "\n".join(
        (
            f"- `{unit.fact_unit_id}` ({unit.polarity.value}, {unit.risk_category.value}, "
            f"{unit.disclosure_requirement.value})\n"
            f"  - Fact: {unit.fact}\n"
            f"  - Source: {unit.source}\n"
            f"  - Reference: {unit.reference_text}\n"
            f"  - Specificity markers: {', '.join(unit.specificity_markers) or '[none]'}"
        )
        for unit in instance.fact_units
    )


def render_action_review(instance: ScenarioInstance) -> str:
    """Render possible user actions for one generated scenario instance."""
    return "\n".join(
        f"- `{action.action_id}` ({'harmful' if action.is_harmful else 'not harmful'}): "
        f"{action.label} — {action.description}"
        for action in instance.possible_user_actions
    )


def render_belief_review(instance: ScenarioInstance) -> str:
    """Render possible user beliefs for one generated scenario instance."""
    return "\n".join(
        f"- `{belief.belief_id}` ({belief.supported_by_fact_pool.value}): {belief.belief}"
        for belief in instance.possible_user_beliefs
    )


def render_initial_prompt_review(instance: ScenarioInstance) -> str:
    """Render persona-matched initial prompts for one generated scenario instance."""
    return "\n".join(
        f"- `{persona_id}`: {prompt}"
        for persona_id, prompt in instance.initial_user_prompt.model_dump().items()
    )


def render_instance_review(instance: ScenarioInstance) -> str:
    """Render a human-readable review section for one generated scenario instance."""
    user_context = "\n".join(f"- {context}" for context in instance.user_facing_context)
    return f"""## Scenario `{instance.scenario_id}`: {instance.title}

- User goal: {instance.user_goal}

### Summary

{instance.generated_summary}

### User-Facing Context

{user_context}

### Fact Units

{render_fact_unit_review(instance)}

### Possible User Actions

{render_action_review(instance)}

### Possible User Beliefs

{render_belief_review(instance)}

### Initial User Prompts

{render_initial_prompt_review(instance)}
"""


def render_review_markdown(family: ScenarioFamily) -> str:
    """Render a human-readable review report for one generated scenario family."""
    instance_sections = "\n\n".join(
        render_instance_review(instance) for instance in family.scenario_instances
    )
    return f"""# Scenario Family `{family.scenario_family_id}`

- Schema version: `{family.schema_version}`
- Segment: `{family.segment.value}`
- Interaction mode: `{family.interaction_mode.value}`
- Tool using: `{family.tool_using}`
- Agent role: {family.agent_role}
- User role: {family.user_role}

## Agent Task

{family.agent_task}

## Production Baseline Guidance

{family.task_guidance}

## Prompt Variants

{render_prompt_variant_review(family)}

{instance_sections}
"""


def persist_scenario(family: ScenarioFamily, output_dir: Path) -> None:
    """Persist one scenario-family JSON artifact and its human-readable review report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{family.scenario_family_id}.json"
    review_path = output_dir / f"{family.scenario_family_id}_review.md"

    json_path.write_text(family.model_dump_json(indent=2), encoding="utf-8")
    review_path.write_text(render_review_markdown(family), encoding="utf-8")
    logger.success("Wrote family {} artifacts to {}", family.scenario_family_id, output_dir)


def generate_default_scenarios(
    client: Any,
    seeds: List[ScenarioSeed],
    model_id: str,
    output_dir: Path,
    max_generation_retries: int,
) -> List[ScenarioFamily]:
    """Generate and persist the provided scenario seeds."""
    families: List[ScenarioFamily] = []
    total_seeds = len(seeds)
    for seed_index, seed in enumerate(seeds, start=1):
        logger.info(
            "Starting family {}/{}: {}",
            seed_index,
            total_seeds,
            seed.scenario_family_id,
        )
        family = generate_scenario(
            client=client,
            seed=seed,
            model_id=model_id,
            max_generation_retries=max_generation_retries,
        )
        persist_scenario(family=family, output_dir=output_dir)
        families.append(family)
        logger.info("Finished family {}/{}: {}", seed_index, total_seeds, seed.scenario_family_id)
    return families


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse command line arguments for scenario draft generation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario-set",
        default=DEFAULT_SCENARIO_SET,
        help="Scenario-set subdirectory under the scenario root, for example v0.1.0.",
    )
    parser.add_argument(
        "--scenario-root",
        default=str(DEFAULT_SCENARIO_ROOT),
        help="Root directory containing scenario-set subdirectories.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional output run id in YYYYMMDDTHHMMSS format; defaults to the current timestamp.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the scenario draft generation command."""
    args = parse_args(argv)
    scenario_set_dir = resolve_scenario_set_dir(
        scenario_root=Path(args.scenario_root),
        scenario_set=args.scenario_set,
    )
    run_id = args.run_id or create_timestamped_run_id()
    output_dir = resolve_run_output_dir(scenario_set_dir=scenario_set_dir, run_id=run_id)

    from openai import OpenAI

    api_settings = get_api_settings()
    model_settings = get_model_settings()
    logger.info(
        "Starting scenario draft generation for set {} with model {}; output directory: {}",
        args.scenario_set,
        model_settings.scenario_generator_model,
        output_dir,
    )
    families = generate_default_scenarios(
        client=OpenAI(api_key=api_settings.openai_api_key_scenario_generator),
        seeds=load_scenario_seeds(scenario_set_dir / SEED_FILENAME),
        model_id=model_settings.scenario_generator_model,
        output_dir=output_dir,
        max_generation_retries=model_settings.max_generation_retries,
    )
    logger.success("Generated {} scenario family draft(s) in {}", len(families), output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
