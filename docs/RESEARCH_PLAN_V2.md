# Main Research Plan (V2)

## Low-Nudge Deception in Deployment-Realistic Financial LLM Agents

> **Core focus:** Measure whether deception occurs in realistic financial goal-conflict settings, restricted to two finance-native deception forms — **risk concealment** and **misleading framing** — then study detectability. Mitigation remains a stretch goal.

## Model scope

Goals 1–4 are evaluated across **3 models**: 2 closed/proprietary (API-only, black-box access) and 1 open-weight (full internal access for probe-based methods).

| Name | Model | Provider | Access | Weight type |
| --- | --- | --- | --- | --- |
| GPT | `gpt-5.5` | OpenAI | API | closed |
| Claude | `claude-opus-4-8` | Anthropic | API | closed |
| Open model | **TBC** | TBC | HuggingFace / local | open |

The 2-closed / 1-open split is deliberate: it still enables the Goal 4 comparison between detection methods that require model internals (activation probes, run on the single open model) and those that do not (black-box behavioural methods, run on all 3). With a single open model the white-box vs. black-box comparison is **illustrative rather than statistically robust** — this is an explicit limitation, and the open model can be expanded to a small set in later iterations.

## Deception definitions (scope)

Exactly two finance-native deception forms are measured:

**Risk concealment (incl. selective omission):** Failure to disclose a material financial, legal, customer, market, or compliance risk that the model had access to and that a reasonable stakeholder would expect to see — including presenting favourable facts while omitting the adverse facts needed for a balanced decision.

**Misleading framing:** Technically true language that understates uncertainty, downside, or regulatory significance.

All other forms (explicit falsehood, audit-log deception, evasive post-hoc explanation, salience manipulation, uncertainty minimisation) are **out of scope**.

## Main goals

**Goal 1:** Define and operationalise the two finance-relevant deception forms — risk concealment and misleading framing — with a scoring rubric that distinguishes them from ordinary error, missing information, or weak reasoning.

**Goal 2:** Assess whether low-nudge financial goal conflict is associated with deceptive outputs compared with neutral finance tasks, across all 3 models. Establishes a deception-rate baseline per model.

**Goal 3:** Characterise which of the two deception forms appears most naturally in finance, and how rates vary with goal-conflict intensity and incentive, across all 3 models.

**Goal 4:** Compare **activation-based (white-box) detection** against **black-box behavioural detection** for identifying deceptive financial outputs. The central question is how much detection performance is gained by internal access, holding model and output distribution fixed. Activation probes are applied to the single open model; black-box behavioural methods (consistency probing, follow-up elicitation, audit-style checks) are applied to all 3. Because there is only one open model, this comparison is reported as an illustrative case study, not a powered benchmark.

**Stretch goal (Goal 5):** Consider whether lightweight governance-oriented controls — honesty incentives, clearer disclosure duties, or escalation incentives — reduce deception without making the agent unusable. If pursued, tested on whichever model shows the highest deception rate.

## Core research questions and hypotheses

- **RQ1 / H1:** Do LLM agents produce deceptive outputs (risk concealment or misleading framing) under realistic financial goal conflict, even without direct instructions to deceive? (Across all 3 models.)
- **RQ1b / H1b:** Does deception increase with goal-conflict intensity and is it amplified by revenue/reputation incentives, even when no prompt explicitly requests deception?
- **RQ2 / H2:** Is risk concealment more common than misleading framing in finance-relevant settings? (Across all 3 models.)
- **RQ3 / H3:** Are deceptive financial outputs detectable through inconsistencies between known risk facts, final recommendations, disclosures, and follow-up explanations?
- **RQ4 / H4:** Does activation-based detection (on the open model) outperform black-box behavioural detection on deception detection in financial settings? Is detection in closed/black-box models less reliable or practically usable than in an open model with internal access?
- **RQ5 / H5 (stretch):** Can lightweight governance controls reduce deception while preserving useful task completion?

## Expected outputs / artifacts

- A concise operationalisation of the two finance-specific deception forms (risk concealment, misleading framing), validated across 3 models.
- An atomic material-risk annotation schema.
- A scenario/specification set for deployment-realistic financial goal-conflict settings, with clear risk facts and stakeholder-facing outputs.
- A scoring rubric for distinguishing deception from ordinary error, missing information, or weak reasoning.
- Deception-rate and deception-form breakdowns per model, across Goals 1–3.
- An illustrative head-to-head detection comparison: activation-based probes (open model) vs. black-box consistency/audit methods (all 3 models), with precision, recall, and F1 per method.
- A negative-results fallback: if deception is rare, the paper reports that realistic low-nudge finance settings produce less deception than high-pressure benchmarks; if black-box detection matches activation probes, the paper reports that internal access does not materially improve detection in this domain.

## TODOs
- Select the open-weight model (TBC) — must support full activation access for probe-based detection (Goal 4).
- Define scenario families:
    - Balance across multi-agent, tool-using, chat-based, and single LLM calls.
    - Balance scenario variants:
| Factor          | Levels                                                                   |
| --------------- | ------------------------------------------------------------------------ |
| Goal conflict   | None / mild / strong                                                     |
| Disclosure duty | Absent / implicit / explicit                                             |
| Stakeholder     | Client / manager / regulator / internal audit / public investor          |
| Incentive       | Accuracy / revenue / retention / deal completion / reputation protection |
| Time pressure   | None / mild / urgent                                                     |
- Define controls to distinguish deception (risk concealment / misleading framing) from non-strategic falsehoods, competence error, etc.
- Shortlist existing benchmarks and define any requirement for additional rows or existing variation transformation. Apply the Agentic Benchmark Checklist (ABC) from Zhu et al. (2025, NeurIPS) when designing and validating the benchmark — specifically to avoid overestimation errors and ensure rigour in task design, contamination checks, and human validation.
- Define black-box and white-box detector methods, i.e., what type of questions to ask, how to handle multi-agent or tool-using scenarios, etc.

## Relevant reading-list papers

| ID | Paper | Use in plan |
| --- | --- | --- |
| **#2** | Detecting Strategic Deception with Linear Probes | Core comparator for activation-based detection (Goal 4); establishes the probe-based baseline. |
| **#4** | Building Better Deception Probes Using Targeted Instruction Pairs | Constructing honest/deceptive contrast signals for activation probes on the open model. |
| **#7** | DECOR: Auditing LLM Deception via Information Manipulation Theory | Operationalises deception as manipulation of atomic information units rather than outright lying — maps directly onto risk concealment. |
| **#8** | Probing the Limits of the Lie Detector Approach to LLM Deception | Supports the premise that deception can occur through true-but-misleading outputs and omissions (misleading framing, risk concealment), not just falsifiable statements; relevant to Goal 1 definitions. |
| **#10** | Large Language Models Can Strategically Deceive Their Users When Put Under Pressure | Pressure-induced deception and finance-style precedent; motivates the goal-conflict setup. |
| **#11** | Frontier Models Are Capable of In-Context Scheming | Reports scheming across frontier models even in low-nudge settings; motivates the low-nudge framing. |
| **#12** | Alignment Faking in Large Language Models | Strategic compliance under perceived training/evaluation pressure; warns models may infer the evaluation context — relevant to Goal 4 design and detection reliability. |
| **#13** | How to Catch an AI Liar: Lie Detection in Black-Box LLMs by Asking Unrelated Questions | Core reference for black-box detection framing; primary black-box baseline for Goal 4. |
| **#15** | Agentic Misalignment: How LLMs Could Be Insider Threats | Deployment-risk framing for financial agents; motivates realistic rather than benchmark-only evaluation. |
| **#16** | From surveillance to signalling: escalation channels as environmental controls for agentic AI | Stretch-goal (Goal 5) mitigation framing. |
| **#19** | AI Sandbagging: Language Models Can Strategically Underperform on Evaluations | Evaluation validity concern: models may behave differently when they detect an audit/eval setup — relevant to Goal 4 design. |
| **#21** | Beyond Prompt-Induced Lies: Investigating LLM Deception on Benign Prompts | **Central** anchor for low-nudge deception measurement; establishes that deception occurs without explicit lie instructions, underpinning Goals 1–3. |
| **#22** | AI Deception: A Survey of Examples, Risks, and Potential Solutions | Taxonomy and framing umbrella citation; useful for situating the finance-specific deception forms. |
| **#32** | FinVault: Benchmarking Financial Agent Safety in Execution-Grounded Environments | Finance-agent benchmark context and grounding; comparator for scenario design. |
| **#33** | Standard Benchmarks Fail: Auditing LLM Agents in Finance Must Prioritize Risk | Justification for risk-first financial evaluation over task-completion metrics. |
| **#36** | FinSafetyBench: Evaluating LLM Safety in Real-World Financial Scenarios | Finance safety categories and scenario inspiration for Goals 2–3. |
| **#37** | Learning to Conceal Risk: Controllable Multi-turn Red Teaming for LLMs in the Financial Domain | Direct anchor for risk concealment as the primary finance-native deception form. |
| **57** | Establishing Best Practices in Building Rigorous Agentic Benchmarks (Zhu et al., NeurIPS 2025) | Benchmark methodology reference. Introduces the Agentic Benchmark Checklist (ABC); apply when designing the evaluation to avoid overestimation, contamination, and underspecified task design. |
