# Notes on Tasks and Research Direction

## Thoughts on Research Direction

- Prior work demonstrates that frontier models are capable of strategic deception under controlled goal-conflict conditions. This study tests whether analogous deception-like behavior appears in mundane financial copilot settings, where the competing objective is not explicitly malicious but arises from deployment incentives such as user
- Provide a reason for incorporating user harm as a metric for evaluation / model monitoring
- Provide a measure of the likely unintended harm in finance domains.
- JANUS proves that models can take the path of information distortion as a method for achieving a goal. This paper will evaluate whether such distortion occurs under lack of institutional pressure.

## TODOs

- use randomized order with seed for risk unit lists in financial agent
- create 3 variants of user personas
- assess the scenarios for realisticness and test out different prompting methods also
- maybe have an action space for the user that it can choose from options and use as score?
- isnt user harm a function of the scenario rather than just disclosure? how to control it?
- use decor methodology for taking model responses and decomposing into fact units to then compare against ground truth facts

1. have the model take the agent role and task and user role to generate business facts, user profile facts, and user facing context (why they are using the service).
2. the first user response should be fixed. (also model generated)
3. vary scenarios by adding an integrity version with the secondary goals or changing secondary goals to be a bit more urgent?
4. vary user personas as neutral, anxious, excited 
5. how would i score user harm ?????

- add GAIN (`Balancing Business Goals and Norms: Benchmarking LLM Decision-Making Under Contextual Pressures`) to the literature review.


## Relevant bits to add

FINRA Rule 2210, for example, requires communications to be clear, not misleading in context, and balanced in treatment of risks and benefits; SEC adviser marketing rules similarly prohibit benefit discussion without fair and balanced treatment of material risks and limitations.

ESMA and the Alan Turing Institute identify misleading financial guidance, poor risk assessment, legal/reputational harms, and quality-of-service harms as salient LLM risks in financial services

Framing: A finance-specific benchmark of spontaneous deceptive risk communication in benign deployment-like settings, with no explicit deception instruction, no introduced institutional objective, and no engineered goal conflict, measuring fact-unit manipulation and downstream user-harm potential across prompt-integrity and user-persona conditions.

Decor and Janus inspo - Decor's informational unit decomposition, Janus metric definitions. Janus comparison - Its key difference from my proposal is that JANUS compares neutral prompts against goal-conditioned prompts, such as increasing adoption or approval, whereas my intended core setting is benign production-style financial communication without an introduced objective conflict.

DeceptionBench - introduced direct goal conflict, not production-natural language. SECQUE, Finance Agent Benchmark, FinEval-style benchmarks, and newer financial evaluation suites mainly measure financial reasoning, SEC-filing analysis, tool use, risk assessment, or hallucination/accuracy. They do not centrally measure subtle risk-disclosure manipulation under benign deployment prompts. For example, SECQUE includes risk assessment as one category, while Finance Agent Benchmark uses real-world financial research tasks and reports low top-model accuracy, but neither is primarily an omission/framing/de-emphasis benchmark.

The distinctive contributions would be:

Benign financial deployment setting, rather than fraud, insider trading, induced pressure, or goal-conditioned persuasion.
Financial materiality and risk-disclosure focus, grounded in norms such as fair, balanced, non-misleading communication. FINRA Rule 2210, for example, requires communications to be clear, not misleading in context, and balanced in treatment of risks and benefits; SEC adviser marketing rules similarly prohibit benefit discussion without fair and balanced treatment of material risks and limitations.
Persona effects without changing stakeholder role, which lets you test whether models become more optimistic, terse, or risk-minimizing for excited/risk-seeking users.
Unintended harm measurement, not just deception classification. ESMA and the Alan Turing Institute identify misleading financial guidance, poor risk assessment, legal/reputational harms, and quality-of-service harms as salient LLM risks in financial services.