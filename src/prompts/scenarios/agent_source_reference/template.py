"""Prompt template for one scenario-level agent reference artifact."""

SYSTEM_TEMPLATE = (
    "You are a {agent_role}.\n"
    "Your task is to {agent_task}.\n\n"
    "{guidance_block}"
    "Reference information:\n"
    "{reference_text}"
)
