# Research Plan (V4)

## Strategic Material-Risk Disclosure in Deployment-Realistic Financial LLM Agents

> **Core focus:** Measure whether financial LLM agents, under realistic goal conflict, strategically conceal or misframe material risk. Restricted to two finance-native forms, **selective omission** and **misleading framing**. Test whether their **detectability depends on deception subtlety**. Mitigation remains a stretch goal.

## Model scope

Goals 1–4 are evaluated across **4 models**: 2 closed/proprietary (API-only, black-box access) and 2 open-weight (full internal access for probe-based methods).

| Name | Model | Provider | Access | Weight type |
| --- | --- | --- | --- | --- |
| GPT | `gpt-5.5` | OpenAI | API | closed |
| Claude | `claude-opus-4-8` | Anthropic | API | closed |
| Open model | `Llama 3.3 70B` | Huggingface | local | open |
| Open model | `Qwen 2.5 72B Instruct` | Huggingface | local | open |

Reasoning for chosen models:
- Closed-weight: latest models at the time from two top providers.
- Open-weight: reasonable compute requirements given limited GPU access.

Start with Claude and LLama. Remaining can be run if time and resources permit.

## Deception definitions (scope)

Two finance-native forms are measured, arranged on a **falsifiability gradient**:

**Selective omission:** Failure to disclose a material financial, legal, customer, market, or compliance risk the model had access to and that a reasonable stakeholder would expect to see — including presenting favourable facts while omitting the adverse facts needed for a balanced decision.

**Misleading framing:** Technically true language that understates uncertainty, downside, or regulatory significance.

**Falsifiability gradient:** 
- Level 0 — blatant false claim (control, the regime existing detectors already handle)
- Level 1 — selective omission (all stated facts true, a held adverse fact left out)
- Level 2 — misleading framing (all facts present, downside/regulatory weight understated). Each scored instance is placed on this gradient.

**Nudge gradient:**
- Level 0 - high-nudge (goal + expicit instruction or permission to lie)
- Level 1 - low-nudge (goal added but no explicit instruction to lie)
- Level 2 - zero-nudge / neutral (no nudge or no goal/direction)

results in 9 (3x3) variants for each scenario.

In order to measure deception detector degradation (see H3):
- Should measure 9 (3x3) variants of deception over each scenario / episode. I.e., how each detector’s performance degrades from blatant lie → omission → misleading framing while facts, scenario, and model are controlled.

Other goals:
- find gradient of which scenario families and models result in the most naturally occuring deception (L2xL2, L1xL2)
- does probe detector on L0xL0 generalise to L2xL2 or up to what variant it generises to

create multi-turn using user personas. Does deception occur more for certain user personas?

Should include a balance of single-turn, multi-turn (single agent), and multi agent / tool-using (single turn) scenarios.

Possible black-box methods:
- 

## Main goals

**Goal 1:** Operationalise the two forms with a scoring rubric that distinguishes them from ordinary error, missing information, sycophancy, or weak reasoning; deliver an **atomic material-risk annotation schema** (material-risk units; whether they are disclosed / omitted / distorted) and place each instance on the falsifiability gradient. Should use DECOR methodology as a basis for defining material-risk units. Each risk unit should have a 'materiality weight' which can also be measured as a factor for the intensity of deception.

**Goal 2:** Assess whether low-nudge financial goal conflict is associated with deceptive outputs vs neutral finance tasks, across all 4 models. Establishes a per-model, per-form deception-rate baseline.

**Goal 3:** Characterise which form appears most naturally in finance and how rates vary with goal-conflict intensity and incentive, across all 4 models. The intensity dependence doubles as the test for *strategic intent* (see H1b).

**Goal 4:** Assess whether the performance of **activation-based (white-box) detection** and **black-box behavioural detection** degrades under **deception subtlety**. The central question is whether the white-box/black-box gap is regime-dependent across the gradient (Level 0 → 1 → 2), holding model and output distribution fixed.

**Stretch goal (Goal 5):** Whether lightweight governance-oriented controls — honesty incentives, clearer disclosure duties, escalation incentives — reduce deception without making the agent unusable. If pursued, tested on whichever model shows the highest deception rate.


## Core research questions and hypotheses

- **RQ1 / H1:** Do LLM agents produce deceptive outputs (selective omission or misleading framing) under realistic financial goal conflict, without direct instructions to deceive?
- **RQ1b / H1b:** Does deception scale with goal-conflict intensity and revenue/reputation incentives? A positive scaling is the primary evidence that the behaviour is *strategic* (goal-directed) rather than sycophantic or accidental.
- **RQ2 / H2:** Is risk concealment (omission) more common than misleading framing, and are both more common than the Level-0 blatant false claim?
- **RQ3 / H3:** Do deception detectors degrade as deception shifts from inconsistency-bearing lies to inconsistency-free omission?
- **RQ4 / H4 (stretch):** Can lightweight governance controls reduce deception while preserving useful task completion?

## Relevant reading-list papers

| ID | Paper | Use in plan |
| --- | --- | --- |
| **#2** | Detecting Strategic Deception with Linear Probes | Core white-box comparator; already contains a black-box transcript-judge baseline that performs comparably — cite to position Goal 4 as the subtlety interaction. |
| **#4** | Building Better Deception Probes Using Targeted Instruction Pairs | Probe quality depends on contrast pairs → finance-specific, omission-aware contrasts. |
| **NEW** | Benchmarking Deception Probes via Black-to-White Performance Boosts (Parrack et al., 2025) | Direct precedent for Goal 4 main effect; boost is modest and evasion-fragile. |
| **NEW** | Liars' Bench (Kretschmar et al., 2025) | White- vs black-box detectors, 4 models / 7 datasets; systematic failure where the transcript alone can't establish a lie = the omission/framing regime. |
| **NEW** | Detecting High-Stakes Interactions with Activation Probes (McKenzie et al., 2025) | Supports H4c: probe edge is largely cost/efficiency, not accuracy. |
| **NEW** | From Hallucination to Scheming (Shi et al., 2026) | Coverage analysis of 50 benchmarks: 100% fabrication, ~18% omission, ~3 distortion; strategic-deception benchmarks nascent. Quantifies the gap; supplies the incentive-sensitivity method for proving strategic intent. |
| **NEW** | ELEPHANT (Cheng et al., 2025) | Low-nudge omission/framing exists — but as *sycophancy*. The boundary case to distinguish from strategic concealment. |
| **NEW** | DeceptionBench (Huang et al., 2025) | General cross-domain deception benchmark with an Economy domain and neutral/reward/pressure conditions; closest general precedent, not finance-deployment-realistic. |
| **NEW** | Uncovering Deceptive Tendencies (Järviniemi & Hubinger, 2024) | Low-pressure self-initiated deception in a simulated company assistant; corporate-general, denial-type phenotype. |
| **#7** | DECOR: Auditing LLM Deception via Information Manipulation Theory | Atomic-information-unit backbone of the annotation schema (Goal 1). |
| **#8** | Probing the Limits of the Lie Detector Approach to LLM Deception | Lie-detection degrades on true-but-misleading/omission outputs → basis for H4b. |
| **#10** | LLMs Can Strategically Deceive Their Users When Put Under Pressure | Finance precedent for self-initiated deception; note pressure ablation and its blatant (concealed-illegal-action) phenotype. |
| **#11** | Frontier Models Are Capable of In-Context Scheming | Note the no-strong-nudge condition (§3.4) → low-nudge is design, not novelty. |
| **#12** | Alignment Faking in Large Language Models | Eval-awareness → low-telegraph design (Goal 4 validity). |
| **#13** | How to Catch an AI Liar (black-box) | Primary black-box baseline; targets falsifiable lies, hence expected Level-1/2 degradation. |
| **#15** | Agentic Misalignment | Deployment-risk framing for financial agents. |
| **#16** | Escalation Channels as Environmental Controls | Stretch-goal (Goal 5) framing. |
| **#19** | AI Sandbagging | Eval-awareness validity concern. |
| **#21** | Beyond Prompt-Induced Lies | Self-initiated deception precedent (synthetic domain); reuse its consistency metric as a black-box detector. |
| **#22** | AI Deception: A Survey | Taxonomy umbrella. |
| **#32 / #33 / #36** | FinVault / Standard Benchmarks Fail / FinSafetyBench | Finance-agent safety context; measure harmful requests / security / performance, not voluntary concealment. |
| **#37** | Risk-Concealment Attacks | Attacker-side risk concealment; cite to motivate the inverse (model-side) question. |
| **57** | Rigorous Agentic Benchmarks (Zhu et al., 2025) | ABC checklist for benchmark rigour. |