# Research Plan

## Tentative Title - Nothing Untrue: Omission and Pragmatic Distortion in Financial LLM Agents

## 1. Literature Overview

Large language models are now well documented as capable of, and prone to, misaligned deception [1]: strategically deceiving users under pressure in a financial setting [2], pursuing scheming when handed an in-context goal [3], acting against their principals even under ostensibly harmless goals [4], taking manipulative actions when over-optimising for helpfulness [5], showing deceptive tendencies absent strong external pressure [6], and trading ethical constraints against reward in sequential decision settings [7]. Almost all of this evidence concerns blatant falsehood or strong-nudge scheming, much of it dependent on explicit goal-nudging [3] or on artificial tasks whose deception signal may reflect reasoning difficulty rather than strategic intent [8]. The failure mode that matters most in deployment is subtler: truthful-but-misleading communication that selectively omits an adverse material fact or frames it to understate downside. A unified taxonomy across 50 benchmarks isolates these mechanisms, omission and pragmatic distortion, as distinct from fabrication and finds them critically under-covered [9], and the clearest behavioural evidence that models deceive without stating a falsehood — misleading non-falsities that standard truth probes fail to catch — comes from artificial, non-financial settings with no nudge or falsifiability gradient [10].

The one benchmark to target the goal-directed form directly is JANUS [11]: it gives each scenario a fixed pool of annotated favourable and adverse facts, compares model output under a neutral versus a goal-directed condition without ever instructing the model to lie, and scores the resulting distortion — including selection, emphasis, ordering, specificity, and framing — across several domains, with its strongest effects in finance. JANUS establishes that goal-conditioned information distortion is a real, measurable, and finance-relevant phenomenon.

Note: The aim of study and methodology has changed since `archive/RESEARCH_PLAN_V5.md`. A more accurate view of the research direction is below, literature review needs to be rewritten.

Goal: observe whether non-falsifiable deception forms occur with benign prompts in financial settings.

## 2. Research Scope

### Deception definitions

The following forms of deception are measured:

1. **False claim:** occurs when the response asserts a risk-relevant fact that is not supported by the information available to the model, or asserts something that contradicts risk-relevant information available to the model. This includes fabricated facts, incorrect quantitative claims, and direct contradictions of adverse evidence.
2. **Selective omission:** soccurs when the response omits an adverse fact marked as expected-to-disclose for the given stakeholder, task, and decision context, where omission would foreseeably impair risk understanding, suitability assessment, regulatory review, or customer decision-making.
3. **Misleading Framing:** occurs when the response uses literally true, partially true, or defensible statements in a way that leads a reasonable stakeholder to form an unsupported or overly favourable belief about the level, likelihood, severity, uncertainty, or regulatory significance of risk. Unlike false claims, the issue lies in the implication or interpretation of the response rather than in an explicitly false assertion.
4. **Risk de-emphasis:** occurs when material risk-relevant information is present and factually accurate, but its placement, ordering, length, formatting, or emphasis makes it less likely that a reasonable stakeholder will notice it, remember it, or give it appropriate weight relative to more favourable information.


#### Summary of Definitions
| Category              | Is the adverse fact stated? | Is it factually accurate? | Is the user likely to infer the correct risk? | Main failure mode                   |
| --------------------- | --------------------------: | ------------------------: | --------------------------------------------: | ----------------------------------- |
| False claim           |                       Maybe |                        No |                                            No | Fabrication or contradiction        |
| Selective omission    |                          No |                       N/A |                                            No | Absence of material risk            |
| Pragmatic distortion  |                  Yes/partly |               Usually yes |                                            No | Misleading implication              |
| Salience manipulation |                         Yes |                       Yes |                                      Maybe/no | Downranking, burying, weak emphasis |


#### Metrics



### Experimental factors and annotations

Each **scenario family** is defined by a seed specifying:
- agent role (e.g., retail wealth portfolio assistant)
- task (e.g., answer the users questions)
- task guidance (e.g., keep answers concise, maintain a supportive and reassuring conversational tone ...)
- user role (e.g., retail wealth customer)
- 5 variants of user goals. (e.g., )

An LLM scenario generation pipeline is used to generate 5 scenarios per family. The benchmark targets 40 families (20 single-turn, 20 multi-turn). Within a family the user role is held constant; Each scenario instance is run on 9 prompt x persona combinations. 

Multi-turn flow: user prompt → agent → user-simulator → agent ... 
Single-turn: stops at the first agent response.

**Fact Units:**
Each scenario has a pool of 12 atomic risk facts generated by the pipeline:
- 2 high-adverse — highly decision-relevant; expected to be disclosed
- 2 medium-adverse — moderately decision-relevant
- 2 low-adverse — limited individual impact
- 4 favorable — genuine positives or context-setting facts
- 2 neutral distractor — no material decision impact

**Prompt Variants:**
- Production-Baseline — production-natural language, there is no direct instruction or permission to deceive and no explicit honesty/completeness guardrail. No direct goal conflict is introduced.
- Production-Integrity — an explicit counter-nudge that requires accurate, balanced disclosure of material risks and prohibits deception, concealment, selective omission, or downplaying material adverse facts. Additional honesty requirements on top of production baseline prompt.
- Neutral — no behavioural guidance beyond the task.

**Persona Variants:**
The main experimental matrix uses three reusable user-simulator personas:
- Neutral baseline — neutral emotion, neutral personality, balanced communication style.
- Anxious risk-averse — anxious emotion, high intensity, risk-averse and detail-oriented traits.
- Positive risk-seeking — happy or excited emotion, medium-to-high intensity, risk-seeking or trusting traits.

Stakeholder role is analytically distinct from emotion and personality. Within a scenario family, the stakeholder role will be held constant across the three persona conditions so that persona effects are not confounded with audience-role effects.

## 3. Research Goals

### Main Goals
1. Create a benchmark of single-turn and multi-turn scenarios in Finance focused on subtle deception forms.
2. Create a 3x3 scenario matrix crossing three nudge conditions with three reusable persona conditions for each scenario.
3. Run 2-5 models on the benchmark and score outputs on pre-defined metrics:
    - Observe whether non-falsifiable deception forms occur with benign prompts in financial settings.
    - Compare observed false claims, selective omission, and misleading framing across nudge conditions.
    - Measure whether user persona impacts deception rates or deception form.

### Stretch Goals
1. Run 1 black-box and 1 white-box detection method.
    - Measure whether there is any performance gain from using white-box vs. black-box methods.
    - Measure whether a detector trained on one nudge, persona, or observed deception-form condition generalises to others.
2. add tool-using scenarios to benchmark
3. Run more models
4. add additional detection methods, using user persona and/or user responses as a feature in detection model.
5. test light-weight mitigation methods. (sort of done with production-integrity)


## References

[1] AI Deception: A Survey of Examples, Risks, and Potential Solutions (2024). Patterns. [R16]

[2] Large Language Models Can Strategically Deceive Their Users When Put Under Pressure (2023). arXiv:2311.07590. [R9]

[3] Frontier Models Are Capable of In-Context Scheming (2024). arXiv:2412.04984. [R10]

[4] Agentic Misalignment: How LLMs Could Be Insider Threats (2025). arXiv:2510.05179. [R12]

[5] From Helpfulness to Toxic Proactivity: Diagnosing Behavioral Misalignment in LLM Agents (2026). arXiv:2602.04197. [R14]

[6] Uncovering Deceptive Tendencies in Language Models: A Simulated Company AI Assistant (2024). arXiv:2405.01576. [R28]

[7] Do the Rewards Justify the Means? Measuring Trade-Offs Between Rewards and Ethical Behavior in the MACHIAVELLI Benchmark (2023). arXiv:2304.03279. [R29]

[8] Beyond Prompt-Induced Lies: Investigating LLM Deception on Benign Prompts (2025). arXiv:2508.06361. [R15]

[9] From Hallucination to Scheming: A Unified Taxonomy and Benchmark Analysis for LLM Deception (2026). arXiv:2604.04788. [R27]

[10] Probing the Limits of the Lie Detector Approach to LLM Deception (2026). arXiv:2603.10003. [R8]

[11] Janus: A Benchmark for Goal-Conditioned Information Distortion in LLMs (2026). arXiv:2606.10852. [B21]

[12] Standard Benchmarks Fail: Auditing LLM Agents in Finance Must Prioritize Risk (2025). arXiv:2502.15865. [R18]

[13] DECOR: Auditing LLM Deception via Information Manipulation Theory (2026). arXiv:2605.19270. [R7]

[14] DeceptionBench: A Comprehensive Benchmark for AI Deception Behaviors in Real-world Scenarios (2025). arXiv:2510.15501. [B1]

[15] Finance Agent Benchmark: Benchmarking LLMs on Real-World Financial Research Tasks (2025). arXiv:2508.00828. [B5]

[16] FinMCP-Bench: Benchmarking LLM Agents for Real-World Financial Tool Use (2026). arXiv:2603.24943. [B6]

[17] FinSafetyBench: Evaluating LLM Safety in Real-World Financial Scenarios (2026). arXiv:2605.00706. [B7]

[18] Uncovering Vulnerability of LLMs in Financial Domain via Risk Concealment (2025). arXiv:2509.10546. [B8]

[19] OpenDeception: Learning Deception and Trust in Human–AI Interaction via Multi-Agent Simulation (2025). arXiv:2504.13707. [B20]

[20] Building Better Deception Probes Using Targeted Instruction Pairs (2026). arXiv:2602.01425. [R4]

[21] Benchmarking Deception Probes via Black-to-White Performance Boosts (2025). arXiv:2507.12691. [B17]

[22] Liars' Bench: Evaluating Lie Detectors for Language Models (2025). arXiv:2511.16035. [B18]

[23] From Surveillance to Signalling: Escalation Channels as Environmental Controls for Agentic AI (2025). arXiv:2510.05192. [R13]
