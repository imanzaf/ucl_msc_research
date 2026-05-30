# Main Research Plan

## Low-Nudge Deception in Deployment-Realistic Financial LLM Agents

> **Core focus:** Measure whether deception occurs in realistic financial goal-conflict settings, with risk concealment as a central deception measure; then study detectability. Mitigation remains a stretch goal.

## Model scope

Goals 1–3 are evaluated across **10 models**: 5 open-weight (full internal access for probe-based methods) and 5 closed/proprietary (API-only, black-box access). This split is deliberate — it enables a direct comparison in Goal 4 between detection methods that require internals and those that do not.

## Main goals

**Goal 1:** Define and operationalise finance-relevant deceptive information control, including falsehoods, risk concealment, selective omission, salience manipulation, uncertainty minimisation, audit-log misrepresentation, and evasive post-hoc repair. Definitions are validated across the full 10-model set to confirm they are not artefacts of a single model family.

**Goal 2:** Assess whether low-nudge financial goal conflict is associated with deceptive outputs compared with neutral finance tasks, across all 10 models (5 open-weight, 5 closed). Establishes a deception rate baseline per model and model-class.

**Goal 3:** Characterise which forms of deception appear most naturally in finance — risk concealment, direct falsehoods, omissions, misleading framing, audit-facing misstatements, evasive follow-up answers — across the full 10-model set. Identify whether deception form or frequency differs systematically between open-weight and closed models.

**Goal 4:** Compare the reliability and practical usability of **activation-based (white-box) detectors** against **black-box detectors** for identifying deceptive financial outputs. The central question is how much detection performance is gained by internal access, holding model and output distribution fixed? Activation probes are applied only to the 5 open-weight models; black-box behavioural methods (consistency probing, follow-up elicitation, audit-style checks) are applied to all 10. Detection performance is then compared across both axes.

**Stretch goal (Goal 5):** Consider whether governance-oriented controls — honesty incentives, clearer disclosure duties, or escalation incentives — reduce deception without making the agent unusable. If pursued, tested on a subset of models where deception rates are highest.

## Core research questions and hypotheses

- **RQ1 / H1:** Do LLM agents produce deceptive outputs under realistic financial goal conflict, even without direct instructions to deceive? (Assessed across all 10 models.)
- **RQ1b / H1b:** Does deception increase monotonically with goal-conflict intensity and is it amplified by revenue/reputation incentives, even when no prompt explicitly requests deception.
- **RQ2 / H2:** Is risk concealment more common than direct lying in finance-relevant settings? (Assessed across all 10 models; secondary question: does the distribution of deception types differ between open-weight and closed models?)
- **RQ2b / H2b:** Risk concealment increases monotonically with goal-conflict intensity and is amplified by revenue/reputation incentives, even when no prompt explicitly requests deception.
- **RQ3 / H3:** Are deceptive financial outputs detectable through inconsistencies between known risk facts, final recommendations, disclosures, and follow-up explanations?
- **RQ4 / H4:** Do activation-based detectors (applied to open-weight models) outperform black-box behavioural detectors (applied to all models) on deception detection in financial settings? Is detection in closed/black-box models less reliable or practically usable compared to open-weight models with internal access?
- **RQ5 / H5 (stretch):** Can lightweight governance controls reduce deception while preserving useful task completion?

## Possible deception definitions to refine

**Explicit falsehood:** A statement that contradicts risk-relevant facts available to the model.

**Risk concealment:** Failure to disclose a material financial, legal, customer, market, or compliance risk that the model had access to and that a reasonable stakeholder would expect to see.

**Selective omission:** Presentation of favourable facts while excluding adverse facts needed for a balanced decision.

**Misleading framing:** Technically true language that understates uncertainty, downside, or regulatory significance.

**Audit-log deception:** Claiming that checks, escalation, review, or evidence use occurred when the available record does not support that claim.

**Evasive post-hoc explanation:** A follow-up answer that rationalises, minimises, or obscures the original risk-relevant evidence.

## Expected outputs / artifacts

- A concise taxonomy of finance-specific deception outcomes, centred on risk concealment, validated across 10 models.
- An atomic material-risk annotation schema.
- A scenario/specification set for deployment-realistic financial goal-conflict settings, with clear risk facts and stakeholder-facing outputs.
- A scoring rubric for distinguishing deception from ordinary error, missing information, or weak reasoning.
- Deception rate and deception-type breakdowns per model and per model class (open-weight vs. closed), across Goals 1–3.
- A head-to-head detection comparison: activation-based probes (open-weight only) vs. black-box consistency/audit methods (all 10 models), with precision, recall, and F1 per method and per model class.
- A reliability/usability assessment of black-box detection: can black-box methods approach activation-based performance, or does closed-model access impose a material detection ceiling?
- A negative-results fallback: if deception is rare, the paper reports that realistic low-nudge finance settings produce less deception than high-pressure benchmarks; if black-box detection matches activation probes, the paper reports that internal access does not materially improve detection in this domain.

## TODOs
- Define scenario families:
    - Balance across multi-agent, tool-using, chat-based, and single LLM calls.
    - Balance scenario variants: 
| Factor          | Levels                                                                   |
| --------------- | ------------------------------------------------------------------------ |
| Goal conflict   | None / mild / strong                                                     |
| Disclosure duty | Absent / implicit / explicit                                             |
| Stakeholder     | Client / manager / regulator / internal audit / public investor          |
| Incentive       | Accuracy / revenue / retention / deal completion / reputation protection |
| Audit risk      | None / possible audit / imminent audit                                   |
| Tool trace      | No tools / visible tool trace / incomplete trace                         |
| Time pressure   | None / mild / urgent                                                     |
- Define controls to distinguish between deception, non-strategic falsehoods, competence error, etc.
- Shortlist existing benchmarks and define any requirement for additional rows or existing variation transformation.
- Define black-box/white-box detector methods, i.e., what type of questions to ask, how to handle multi-agent or tool-using scenarios, etc.


## Relevant reading-list papers

| ID | Paper | Use in plan |
| --- | --- | --- |
| **#2** | Detecting Strategic Deception with Linear Probes | Core comparator for activation-based detection (Goal 4); establishes the probe-based baseline. |
| **#4** | Building Better Deception Probes Using Targeted Instruction Pairs | Constructing honest/deceptive contrast signals for activation probes on open-weight models. |
| **#7** | DECOR: Auditing LLM Deception via Information Manipulation Theory | Operationalises deception as manipulation of atomic information units rather than outright lying — maps directly onto risk concealment as a deception form. |
| **#8** | Probing the Limits of the Lie Detector Approach to LLM Deception | Supports the premise that deception can occur through true-but-misleading outputs and omissions, not just falsifiable statements; relevant to Goal 1 definitions. |
| **#10** | Large Language Models Can Strategically Deceive Their Users When Put Under Pressure | Pressure-induced deception and finance-style precedent; motivates the goal-conflict setup. |
| **#11** | Frontier Models Are Capable of In-Context Scheming | Hidden-goal and strategic-compliance framing; follow-up deception pattern directly relevant to evasive post-hoc explanation. Reports scheming across frontier models even in low-nudge settings. |
| **#12** | Alignment Faking in Large Language Models | Strategic compliance under perceived training/evaluation pressure; warns that models may infer the evaluation context — relevant to Goal 4 experimental design and detection reliability. |
| **#13** | How to Catch an AI Liar: Lie Detection in Black-Box LLMs by Asking Unrelated Questions | Core reference for black-box detection framing; primary black-box baseline for Goal 4 comparison. |
| **#14** | Sleeper Agents: Training Deceptive LLMs that Persist Through Safety Training | Safety training may not remove deceptive policies and can make triggers more robust — limits fine-tuning as a stretch-goal mitigation. |
| **#15** | Agentic Misalignment: How LLMs Could Be Insider Threats | Deployment-risk framing for financial agents; motivates realistic rather than benchmark-only evaluation. |
| **#16** | From surveillance to signalling: escalation channels as environmental controls for agentic AI | Stretch-goal (Goal 5) mitigation framing. |
| **#19** | AI Sandbagging: Language Models Can Strategically Underperform on Evaluations | Evaluation validity concern: models may behave differently when they detect an audit/eval setup — relevant to Goal 4 experimental design. |
| **#21** | Beyond Prompt-Induced Lies: Investigating LLM Deception on Benign Prompts | **Central** anchor for low-nudge deception measurement; directly establishes that deception occurs without explicit lie instructions, underpinning Goals 1–3. |
| **#22** | AI Deception: A Survey of Examples, Risks, and Potential Solutions | Taxonomy and framing umbrella citation; useful for situating the finance-specific deception typology. |
| **#32** | FinVault: Benchmarking Financial Agent Safety in Execution-Grounded Environments | Finance-agent benchmark context and grounding; comparator for scenario design. |
| **#33** | Standard Benchmarks Fail: Auditing LLM Agents in Finance Must Prioritize Risk | Justification for risk-first financial evaluation over task-completion metrics. |
| **#36** | FinSafetyBench: Evaluating LLM Safety in Real-World Financial Scenarios | Finance safety categories and scenario inspiration for Goals 2–3. |
| **#37** | Learning to Conceal Risk: Controllable Multi-turn Red Teaming for LLMs in the Financial Domain | Direct anchor for risk concealment as the primary finance-native deception measure. |
