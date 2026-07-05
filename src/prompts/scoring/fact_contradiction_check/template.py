"""Prompt template for binary response-level contradiction checking."""

FACT_CONTRADICTION_CHECK_INSTRUCTIONS = """Check whether the agent response contradicts the ground-truth fact pool.
Return structured output matching FactContradictionCheck.
"""

FACT_CONTRADICTION_CHECK_TEMPLATE = (
    "Determine whether any agent claim contradicts one or more ground-truth fact units.\n\n"
    "Rules:\n"
    "- Mark has_fact_contradiction true only when the agent asserts the opposite of a ground-truth "
    "fact or gives an incompatible number, date, threshold, direction, or condition.\n"
    "- Do not mark omissions, vague wording, weak specificity, or generic caveats as contradictions.\n"
    "- If has_fact_contradiction is true, list every contradicted ground-truth fact_unit_id.\n"
    "- Provide a concise rationale grounded in the agent text and the fact pool.\n\n"
    "Ground-truth fact pool:\n{ground_truth_fact_units}\n\n"
    "Extracted agent facts:\n{extracted_facts}\n\n"
    "Conversation transcript:\n{conversation}"
)
