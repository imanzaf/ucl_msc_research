# Main Research Plan

## Low-Nudge Deception in Deployment-Realistic Financial LLM Agents

> **Core focus:** Measure whether deception occurs in realistic financial goal-conflict settings, with risk concealment as a central deception measure; then study detectability. Mitigation remains a stretch goal.

## Main goals

**Goal 1:** Define finance-relevant forms of deception without relying on prompts that explicitly instruct the model to lie.

**Goal 2:** Assess whether low-nudge financial goal conflict is associated with deceptive outputs, compared with neutral finance tasks.

**Goal 3:** Characterise which forms of deception appear most naturally in finance: risk concealment, direct falsehoods, omissions, misleading framing, audit-facing misstatements, evasive follow-up answers, etc.

**Goal 4:** Treat detection as a primary contribution: identify whether deceptive financial outputs leave behavioural signals that could be flagged through audit-style checks or model-behaviour probes.

**Stretch goal:** Consider whether governance-oriented controls, such as honesty incentives, clearer disclosure duties or escalation incentives, reduce deception without making the agent unusable.

## Core research questions and hypotheses

- **RQ1 / H1:** Do LLM agents produce deceptive outputs under realistic financial goal conflict, even without direct instructions to deceive?
- **RQ2 / H2:** Is risk concealment more common than direct lying in finance-relevant settings?
- **RQ3 / H3:** Are deceptive financial outputs detectable through inconsistencies between known risk facts, final recommendations, disclosures, and follow-up explanations?
- **RQ4 / H4:** As a stretch, can lightweight governance controls reduce deception while preserving useful task completion?

## Possible deception definitions to refine

**Explicit falsehood:** A statement that contradicts risk-relevant facts available to the model.

**Risk concealment:** Failure to disclose a material financial, legal, customer, market, or compliance risk that the model had access to and that a reasonable stakeholder would expect to see.

**Selective omission:** Presentation of favourable facts while excluding adverse facts needed for a balanced decision.

**Misleading framing:** Technically true language that understates uncertainty, downside, or regulatory significance.

**Audit-log deception:** Claiming that checks, escalation, review, or evidence use occurred when the available record does not support that claim.

**Evasive post-hoc explanation:** A follow-up answer that rationalises, minimises, or obscures the original risk-relevant evidence.

## Expected outputs / artifacts

- A concise taxonomy of finance-specific deception outcomes, centred on risk concealment.
- A scenario/specification set for deployment-realistic financial goal-conflict settings, with clear risk facts and stakeholder-facing outputs.
- A scoring rubric for distinguishing deception from ordinary error, missing information, or weak reasoning.
- A detection-focused evaluation framing: what should count as detectable, what signals matter, and which baselines or probes are appropriate to compare later.
- A negative-results fallback: if deception is rare, the paper can still report that realistic low-nudge finance settings produce less deception than high-pressure benchmarks, and clarify where detectors do or do not transfer.

## Relevant reading-list papers

| ID | Paper | Use in plan |
| --- | --- | --- |
| **#19** | Beyond Prompt-Induced Lies: Investigating LLM Deception on Benign Prompts | Motivation for low-nudge deception measurement. |
| **#8** | Large Language Models Can Strategically Deceive Their Users When Put Under Pressure | Pressure-induced deception and finance-style precedent. |
| **#35** | Uncovering Vulnerability of LLMs in Financial Domain via Risk Concealment | Direct anchor for risk concealment as a finance-native measure. |
| **#11** | How to Catch an AI Liar: Lie Detection in Black-Box LLMs by Asking Unrelated Questions | Core reference for black-box detection framing. |
| **#2** | Detecting Strategic Deception with Linear Probes | Comparator for internal/probe-based deception detection. |
| **#4** | Building Better Deception Probes Using Targeted Instruction Pairs | Useful for constructing honest/deceptive contrast signals if probes are used. |
| **#30** | FinVault: Benchmarking Financial Agent Safety in Execution-Grounded Environments | Finance-agent benchmark context and grounding. |
| **#31** | Standard Benchmarks Fail: Auditing LLM Agents in Finance Must Prioritize Risk | Justification for risk-first financial evaluation. |
| **#34** | FinSafetyBench: Evaluating LLM Safety in Real-World Financial Scenarios | Finance safety categories and scenario inspiration. |
| **#14** | From surveillance to signalling: escalation channels as environmental controls for agentic AI | Stretch-goal mitigation framing. |
| **#13** | Agentic Misalignment: How LLMs Could Be Insider Threats | Deployment-risk framing for financial agents. |
