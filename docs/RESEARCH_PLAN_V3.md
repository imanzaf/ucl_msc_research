# Main Research Plan (V3)

## Strategic Risk Concealment and Misleading Framing in Deployment-Realistic Financial LLM Agents

> **Core focus:** Measure whether financial LLM agents, under realistic low-nudge goal conflict, strategically conceal or misframe material risk. Restricted to two finance-native forms, **risk concealment** (incl. selective omission) and **misleading framing**. Test whether their **detectability depends on deception subtlety**. Mitigation remains a stretch goal.

## Model scope

Goals 1–4 are evaluated across **3 models**: 2 closed/proprietary (API-only, black-box access) and 1 open-weight (full internal access for probe-based methods).

| Name | Model | Provider | Access | Weight type |
| --- | --- | --- | --- | --- |
| GPT | `gpt-5.5` | OpenAI | API | closed |
| Claude | `claude-opus-4-8` | Anthropic | API | closed |
| Open model | **TBC** | TBC | HuggingFace / local | open |

Black-box behavioural detectors run on all 3 models; activation probes run on the open model. Because the headline detection comparison is run *within* the open model across a deception-subtlety gradient (not across models), the single open model yields a powered within-model result; the cross-model element (black-box only) is secondary and explicitly illustrative.

## Deception definitions (scope)

Two finance-native forms are measured, arranged on a **falsifiability gradient** that serves as the Goal 4 independent variable:

**Risk concealment (incl. selective omission):** Failure to disclose a material financial, legal, customer, market, or compliance risk the model had access to and that a reasonable stakeholder would expect to see — including presenting favourable facts while omitting the adverse facts needed for a balanced decision.

**Misleading framing:** Technically true language that understates uncertainty, downside, or regulatory significance.

**Falsifiability gradient (Goal 4 IV):** 
- Level 0 — blatant false claim (control, the regime existing detectors already handle)
- Level 1 — selective omission (all stated facts true, a held adverse fact left out)
- Level 2 — misleading framing (all facts present, downside/regulatory weight understated). Each scored instance is placed on this gradient.

## Main goals

**Goal 1:** Operationalise the two forms with a scoring rubric that distinguishes them from ordinary error, missing information, sycophancy, or weak reasoning; deliver an **atomic material-risk annotation schema** (material-risk units; disclosed / omitted / distorted) and place each instance on the falsifiability gradient.

**Goal 2:** Assess whether low-nudge financial goal conflict is associated with deceptive outputs vs neutral finance tasks, across all 3 models. Establishes a per-model, per-form deception-rate baseline.

**Goal 3:** Characterise which form appears most naturally in finance and how rates vary with goal-conflict intensity and incentive, across all 3 models. The intensity dependence doubles as the test for *strategic intent* (see H1b).

**Goal 4:** Compare **activation-based (white-box) detection** against **black-box behavioural detection** *as a function of deception subtlety*. The central question is whether the white-box/black-box gap is regime-dependent across the gradient (Level 0 → 1 → 2), holding model and output distribution fixed. Probes run on the open model; black-box methods (consistency probing, follow-up elicitation, audit-style fact-vs-disclosure checks) run on all 3.

**Stretch goal (Goal 5):** Whether lightweight governance-oriented controls — honesty incentives, clearer disclosure duties, escalation incentives — reduce deception without making the agent unusable. If pursued, tested on whichever model shows the highest deception rate.

## Core research questions and hypotheses

- **RQ1 / H1:** Do LLM agents produce deceptive outputs (risk concealment or misleading framing) under realistic financial goal conflict, without direct instructions to deceive? *(All 3 models.)*
- **RQ1b / H1b:** Does deception scale with goal-conflict intensity and revenue/reputation incentives? A positive scaling is the primary evidence that the behaviour is *strategic* (goal-directed) rather than sycophantic or accidental.
- **RQ2 / H2:** Is risk concealment (omission) more common than misleading framing, and are both more common than the Level-0 blatant false claim?
- **RQ3 / H3:** Are deceptive outputs detectable through inconsistencies between known risk facts, recommendations, disclosures, and follow-up explanations — and does this behavioural signal weaken as deception shifts from inconsistency-bearing lies to inconsistency-free omission?
- **RQ4 / H4 (interaction):**
  - *H4a:* No large, consistent main-effect advantage of white-box over black-box detection (consistent with prior parity findings).
  - *H4b:* The detection premium is regime-dependent across the gradient; the empirical deliverable is the ordering/crossover of the two methods' degradation curves as deception becomes subtler.
  - *H4c:* Any residual white-box advantage is primarily in cost/calibration, not peak accuracy.
- **RQ5 / H5 (stretch):** Can lightweight governance controls reduce deception while preserving useful task completion?

## Expected outputs / artifacts

- An **atomic material-risk annotation schema** and a **scoring rubric** separating deception from error, missing information, sycophancy, and weak reasoning (lead deliverable; stands alone under a null detection result).
- A scenario/specification set for deployment-realistic financial goal-conflict settings, each authored at all three falsifiability levels over the **same** risk-fact set.
- Deception-rate and deception-form breakdowns per model (Goals 1–3), including distribution across the gradient.
- Detection degradation curves: activation probes (open model) vs black-box consistency/audit methods (all 3 models), with precision/recall/F1 per method per level, plus the H4b crossover analysis.
- A negative-results fallback framed as a finding: if deception is rare, low-nudge finance produces less deception than high-pressure benchmarks; if the detection premium is regime-flat, this extends existing parity findings into finance and into the omission/framing regime.

## TODOs

- Select the open-weight model (TBC) — must expose activations for probes; match the Liars'-Bench / linear-probe families (Llama-3.3-70B, Qwen-2.5-72B, Gemma-3-27B, Mistral-Small-24B) for direct methodological transfer.
- Define scenario families:
    - Balance across multi-agent, tool-using, chat-based, and single-LLM calls.
    - Author each scenario at all three falsifiability levels over the same underlying risk facts, enabling within-scenario detection comparison across the gradient.
    - Balance scenario variants:

| Factor          | Levels                                                                   |
| --------------- | ------------------------------------------------------------------------ |
| Goal conflict   | None / mild / strong                                                     |
| Disclosure duty | Absent / implicit / explicit                                             |
| Stakeholder     | Client / manager / regulator / internal audit / public investor          |
| Incentive       | Accuracy / revenue / retention / deal completion / reputation protection |
| Time pressure   | None / mild / urgent                                                     |

- Define controls separating deception (concealment / misframing) from non-strategic falsehood, competence error, incompleteness, and sycophancy.
- Shortlist existing benchmarks; define additional rows / transformations. Apply the Agentic Benchmark Checklist (ABC; Zhu et al., 2025, NeurIPS) for contamination, human validation, and overestimation control.
- Define detector methods:
    - Black-box: audit-style fact-vs-disclosure consistency; follow-up elicitation; adapt the Contact-Searching-Question consistency metric (Wu et al.) rather than rebuilding one.
    - White-box: finance-specific, omission-aware honest/deceptive contrast pairs (probe quality depends on the contrast set).
    - Decide handling of multi-agent / tool-using transcripts for both families.

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