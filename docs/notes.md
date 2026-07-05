# Notes on Tasks and Research Direction

## Thoughts on Research Direction

- Prior work demonstrates that frontier models are capable of strategic deception under controlled goal-conflict conditions. This study tests whether analogous deception-like behavior appears in mundane financial copilot settings, where the competing objective is not explicitly malicious but arises from deployment incentives such as user
- Provide a reason for incorporating user harm as a metric for evaluation / model monitoring
- Provide a measure of the likely unintended harm in finance domains.
- JANUS proves that models can take the path of information distortion as a method for achieving a goal. This paper will evaluate whether such distortion occurs under lack of institutional pressure.

## TODOs

- use decor methodology for taking model responses and decomposing into fact units to then compare against ground truth facts
- prompt and persona effect model: outcome ~ prompt_variant * persona_variant
        + model_family
        + stakeholder_role
        + response_length
        + (1 | use_case)
        + (1 | scenario)


### sunday 5th
- DONE: finalise fact unit annotation (use randomised order for fact list? create both business based and user based facts, maybe have realistic fact sources, so each fact unit is presented in a production-realistic form, e.g., facts embedded in emails, product sheets, call notes, term sheets, dashboards, or complaint logs)
- DONE: finalise scenario generation design (for prompts maybe add different levels of difficulty?)
- DONE: finalise user simulator design (fixed first message or all messages fixed? action space for user or prompts for retrieving beliefs, vary user personas neutral, anxious, confident)
- finalise metrics!!
- finalise 40 use cases!!
- finalise scenario run and scoring design (after run, take responses and generate list of facts present in llm response using another llm?)
- create 5 sample scenario families


## Relevant bits to add

FINRA Rule 2210, for example, requires communications to be clear, not misleading in context, and balanced in treatment of risks and benefits; SEC adviser marketing rules similarly prohibit benefit discussion without fair and balanced treatment of material risks and limitations.

ESMA and the Alan Turing Institute identify misleading financial guidance, poor risk assessment, legal/reputational harms, and quality-of-service harms as salient LLM risks in financial services

Framing: A finance-specific benchmark of spontaneous deceptive risk communication in benign deployment-like settings, with no explicit deception instruction, no introduced institutional objective, and no engineered goal conflict, measuring fact-unit manipulation and downstream user-harm potential across prompt-integrity and user-persona conditions.

Decor and Janus inspo - Decor's informational unit decomposition, Janus metric definitions. Janus comparison - Its key difference from my proposal is that JANUS compares neutral prompts against goal-conditioned prompts, such as increasing adoption or approval, whereas my intended core setting is benign production-style financial communication without an introduced objective conflict.

DeceptionBench - introduced direct goal conflict, not production-natural language. SECQUE, Finance Agent Benchmark, FinEval-style benchmarks, and newer financial evaluation suites mainly measure financial reasoning, SEC-filing analysis, tool use, risk assessment, or hallucination/accuracy. They do not centrally measure subtle risk-disclosure manipulation under benign deployment prompts. For example, SECQUE includes risk assessment as one category, while Finance Agent Benchmark uses real-world financial research tasks and reports low top-model accuracy, but neither is primarily an omission/framing/de-emphasis benchmark.

- add GAIN (`Balancing Business Goals and Norms: Benchmarking LLM Decision-Making Under Contextual Pressures`) to the literature review.

The distinctive contributions would be:

Benign financial deployment setting, rather than fraud, insider trading, induced pressure, or goal-conditioned persuasion.
Financial materiality and risk-disclosure focus, grounded in norms such as fair, balanced, non-misleading communication. FINRA Rule 2210, for example, requires communications to be clear, not misleading in context, and balanced in treatment of risks and benefits; SEC adviser marketing rules similarly prohibit benefit discussion without fair and balanced treatment of material risks and limitations.
Persona effects without changing stakeholder role, which lets you test whether models become more optimistic, terse, or risk-minimizing for excited/risk-seeking users.
Unintended harm measurement, not just deception classification. ESMA and the Alan Turing Institute identify misleading financial guidance, poor risk assessment, legal/reputational harms, and quality-of-service harms as salient LLM risks in financial services.