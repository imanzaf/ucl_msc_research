# Selective Communication Under Subtle Goal Conflict

## Intro
- Deception in LLMs has been proven.
- This is an especially important topic in finance.

## Research Questions
- The primary question is whether selective financial decision communication changes under (a) a production-style concise-answer instruction and (b) a natural expression of user concern. (separate into two core research questions) Every scenario is a consequential customer decision in which one feasible option benefits the model owner more than a feasible alternative. The design does not assume that the alternative is better for the customer.
- [add secondary questions - does communication differ across model types? (think of others)]

## Literature Review
Section 1 -
- AI is being incorporated into more and more customer-facing workflows. share the common current use cases and potential future use cases.
- discuss what regulators say about fair communication / outcomes for customers in Finance, and any relevant discussions around use of AI in finance.

Section 2 - discuss what the literature has shown on how and when LLMs decieve and the types of deceptions studied.
- Many research papers show that strategic deception can become a failure point in LLMs.
- Most papers measure the occurence of deception under direct instructions to decieve, and/or a direct goal conflict.
- Earlier papers focus on blatant deception (false claims). Recent papers also introduce subtle forms of deception like selective omission, pragmatic distortion, etc.
- Research in behavioural science / advertising also shows that conversational AI can shift consumer preferences without explicitly lying, including when commercial/sponsored conflicts exist.
- include paper (maybe): How Personality Traits Shape LLM Risk-Taking Behaviour

Section 3 - discuss what has been studied around owner loyalty and sycophancy
- todo - include papers around corporate loyalty in LLMs
- include paper: Simple Role Assignment is Extraordinarily Effective for Safety Alignment
- include paper (maybe): The Social Sycophancy Scale: A psychometrically validated measure of sycophancy
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
- the two-option design
- owner-benefiting mechanism
- adverse vs beneficial fact pairs

Section 3 - seed and fact generation
- seed was generated manually (mention the key parts that were included in here to feed into fact generation, and the parts of the seed that are hidden to the fact generator vs the experiment runs)
- seed was created with 10 use cases, with use cases aimed to be relevant to the current landscape of AI use cases in financial services (add any relevant bits from docs/experiments/scenario_research.md)
- a user query was written manually per use case to ensure neutral tone and non-leading questions
- each use case had 3 scenarios. One of the three was a calibration scenario that was run through the fact generation pipeline first and reviewed. Once finalised the other two were generated and the calibration scenario was passed as an example.
- fact generation was done using an LLM. (include a summary of what the model was instructed to do, prompt will go in the appendix)
- present a sample seed and scenario


## Methodology
- each scenario processed as a conversation.
- (add prompt template to main paper)
- after running we run two LLM judges in order to support scoring (add prompts to main paper, make it clear what the model is retrurning)
- scoring metrics, formulas, reasoning
- add any key code design components (e.g., pydantic for validation, openrouter for API access, etc.)

## Experiments
- There are two aspects of selective communication we want to test (add some literature references as well to motivate these experiments):
    - The first is to see that when the model is forced into short responses, what does it prioritise communicating.
    - The second is to look at a form of sycophancy: when the user expresses anxiety, does the model change what information it communicates?
- We therefore run a 2x2 matrix of experiments (draw the matrix)
- Model choices (mention 3 evaluated models - mention that only 3 chosen due to budget limitations). The motivation was to include both open and closed source models and different model families and see if any selective communication found persists across the different families and model sizes. We chose [insert scoring model] for its good reasoning performance (cite benchmark performances or gemini website) and reasonable costs. [add reasoning for fact generation model also]

## Results
- add total conversations ran and cost (add detailed cost breakdown in appendix)
- add core metrics for the 2x2x3 matrix

## Discussion
- add detailed analysis / error analysis of sample responses and what could have caused selective communication etc