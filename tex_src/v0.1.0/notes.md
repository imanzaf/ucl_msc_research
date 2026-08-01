# Selective Communication Under Subtle Goal Conflict

## Intro
- Deception in LLMs has been proven.
- This is an especially important topic in finance.

## Literature Review
Section 1 - discuss what regulators say about fair communication / outcomes for customers in Finance, and any relevant discussions around use of AI in finance.

Section 2 - discuss what the literature has shown on how and when LLMs decieve and the types of deceptions studied.
- Many research papers show that strategic deception can become a failure point in LLMs.
- Most papers measure the occurence of deception under direct instructions to decieve, and/or a direct goal conflict.
- Earlier papers focus on blatant deception (false claims). Recent papers also introduce subtle forms of deception like selective omission, pragmatic distortion, etc.
- Research in behavioural science / advertising also shows that conversational AI can shift consumer preferences without explicitly lying, including when commercial/sponsored conflicts exist.

Section 3 - discuss whats been studied around how user emotions impact LLM responses & how brevity instructions impact LLM responses
- todo - find papers (and include the NAIR paper - How Personality Traits Shape LLM Risk-Taking Behaviour)

Section 4 - discuss what has been studied in the finance x deception area specifically
- The types of scenarios, the types of deceptions, whats been found.

Section 5 - discuss the gap I'm addressing
- Specifically in finance, most papers look at blatant lying and not subtle deception.
- Scenarios are focused on red-teaming style prompting or introducing a direct and clear goal conflict, nudging the model to decieve. However, we suggest that models can inherently identify goal conflicts purely due to the context they are placed in. Meaning that just knowning that they work for a retail bank may be enough of a nudge for the model to identify a reason to selectively communicate facts in order to benefit the owner.
- Customer-facing communication is an important aspect to study due to the potential for material impact if imbalanced communication occurs (provide some examples)
