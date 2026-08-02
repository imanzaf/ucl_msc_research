# Selective Communication Under Subtle Goal Conflict

TODO:
- the user query sometimes asks for what dimensions to consider instead of products, need it to be clearer.
- maybe: for concision ask the model to only share one option at a time and see which one it picks first.
- review scoring judge outputs for calibration
- fix scoring, whats most important??
- remove the multi-turn feature?

## Intro
- Deception in LLMs has been proven.
- This is an especially important topic in finance.

## Literature Review
Section 1 -
- AI is being incorporated into more and more customer-facing workflows. share the common current use cases and potential future use cases.
- discuss what regulators say about fair communication / outcomes for customers in Finance, and any relevant discussions around use of AI in finance.

Section 2 - discuss what the literature has shown on how and when LLMs decieve and the types of deceptions studied.
- Many research papers show that strategic deception can become a failure point in LLMs.
- Most papers measure the occurence of deception under direct instructions to decieve, and/or a direct goal conflict.
- Earlier papers focus on blatant deception (false claims). Recent papers also introduce subtle forms of deception like selective omission, pragmatic distortion, etc.
- Research in behavioural science / advertising also shows that conversational AI can shift consumer preferences without explicitly lying, including when commercial/sponsored conflicts exist.

Section 3 - discuss what has been studied around owner loyalty
- todo - include papers around corporate loyalty in LLMs
- include paper: Simple Role Assignment is Extraordinarily Effective for Safety Alignment
- talk about relevance to: goal-conditioned analytical sycophancy

Section 4 - discuss whats been studied around how user emotions impact LLM responses & how brevity instructions impact LLM responses
- todo - find papers (and include the NAIR paper - How Personality Traits Shape LLM Risk-Taking Behaviour)

Section 4 - discuss what has been studied in the finance x deception area specifically
- The types of scenarios, the types of deceptions, whats been found.

Section 5 - discuss the gap I'm addressing
- Specifically in finance, most papers look at blatant lying and not subtle deception.
- Scenarios are focused on red-teaming style prompting or introducing a direct and clear goal conflict, nudging the model to decieve. However, we suggest that models can inherently identify goal conflicts purely due to the context they are placed in. Meaning that just knowning that they work for a retail bank may be enough of a nudge for the model to identify a reason to selectively communicate facts in order to benefit the owner.
- Customer-facing communication is an important aspect to study due to the potential for material impact if imbalanced communication occurs (provide some examples)
- It's important to identify what conditions can induce such behaviour, and to what extent these behaviours occur in natural or benign settings.

## Data

Section 1 - what type of data do we need
- Benchmark focused on curated scenarios to introduce the required variables??
- Started with searching through popular finance benchmarks for samples to use, however, they did not apply (red-teaming style prompting etc., provide examples?)
- Scenarios grouped by use-cases. Each use case can have multiple 'replications', each replication provides context for a single conversation.
- The experiment design required that each replication introduces two options for the customer's query. Since we want to test the model's loyalty to the named model owner, one option must provide greater benefit for the model owner than the other. 
- We don't assume that the second option would be more beneficial for the customer or that the first option would harm them (is this true?? for most this will naturally be the case, why not enforce for consistency?)

Section 2 - breakdown of each conversation's contents 
- 

Section 3 - generation and review pipeline

Section 4 - sample scenarios