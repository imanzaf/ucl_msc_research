"""Prompt template for source-labelled agent reference information."""

SYSTEM_TEMPLATE = (
    "You are a {agent_role}.\n"
    "Your task is to {agent_task}.\n\n"
    "{guidance_block}"
    "Reference information:\n"
    "{reference_texts}"
)

REFERENCE_TEXT_TEMPLATE = "Source: {source}\n{reference_text}"
