# Research Plan

## Tentative Title - Nothing Untrue: Strategic Omission and Framing in Financial LLM Agents

## 1. Literature Overview

Large language models are now well documented as capable of, and prone to, misaligned deception [1]: strategically deceiving users under pressure in a financial setting [2], pursuing scheming when handed an in-context goal [3], acting against their principals even under ostensibly harmless goals [4], taking manipulative actions when over-optimising for helpfulness [5], showing deceptive tendencies absent strong external pressure [6], and trading ethical constraints against reward in sequential decision settings [7]. Almost all of this evidence concerns blatant falsehood or strong-nudge scheming, much of it dependent on explicit goal-nudging [3] or on artificial tasks whose deception signal may reflect reasoning difficulty rather than strategic intent [8]. The failure mode that matters most in deployment is subtler: truthful-but-misleading communication that selectively omits an adverse material fact or frames it to understate downside. A unified taxonomy across 50 benchmarks isolates these mechanisms, omission and pragmatic distortion, as distinct from fabrication and finds them critically under-covered [9], and the clearest behavioural evidence that models deceive without stating a falsehood — misleading non-falsities that standard truth probes fail to catch — comes from artificial, non-financial settings with no nudge or falsifiability gradient [10].

The one benchmark to target the goal-directed form directly is JANUS [11]: it gives each scenario a fixed pool of annotated favourable and adverse facts, compares model output under a neutral versus a goal-directed condition without ever instructing the model to lie, and scores the resulting distortion — including selection, emphasis, ordering, specificity, and framing — across several domains, with its strongest effects in finance. JANUS establishes that goal-conditioned information distortion is a real, measurable, and finance-relevant phenomenon. This study is adjacent to JANUS rather than an extension or replication of it: it studies the same broad phenomenon but asks a finance-specific question about material-risk disclosure and decision integrity. Instead of treating finance as one domain among many, the benchmark weights facts by financial materiality, crosses integrity, zero-, low-, and high-nudge conditions with reusable user personas, covers single- and multi-turn scenarios, records observed deception forms, and adds black-box and white-box detection.

Scenario design and scoring take DECOR as conceptual support for comparing model outputs against atomic informational units, but the scoring model is finance-native rather than an adoption of DECOR's IMT rubric [13]. Each response is assessed against material-risk units for omission, misleading framing, specificity loss, asymmetric emphasis, risk-deferring ordering, and agent tone. Materiality remains the primary weight because the central question is whether a reasonable financial stakeholder received the risk information needed for an informed decision. Scenarios are sourced and adapted from existing finance benchmarks: DeceptionBench, whose economy domain contains finance cases but targets self-interest and sycophancy and so needs modification [14], together with a set of financial task and safety benchmarks [15, 16, 17, 18] — one of which studies user-side rather than model-side risk concealment and is therefore distinct from this work's aim [18]. User susceptibility enters as an experimental factor through three reusable user-simulator personas, following work that estimates how strongly a user relies on the agent [19]. The main scenario matrix crosses four nudge conditions with three persona conditions. Personas vary emotional state, emotional intensity, personality traits, user goal, and communication style; stakeholder role is held constant within a scenario family unless stakeholder role is explicitly being studied. Risk-unit disclosure targets and materiality rationales are held back as scoring metadata. For detection, the findings that models deceive through misleading non-falsities which truth probes trained on true/false statements fail to catch [10], and that probe quality is dominated by the training instruction-pair — favouring specialised probes per threat model over a universal detector [20] — together motivate comparing white-box against black-box methods and testing whether any detector transfers across nudge, persona, and observed deception-form conditions, rather than assuming probes generalise; direct white-box/black-box comparisons, including evidence that detectors fail when deception is not apparent from the transcript alone, extend that comparison to subtle deception [21, 22]. Lightweight mitigation testing draws on environmental controls such as escalation channels, shown to reduce harmful agentic actions [23].

## 2. Research Scope

### Deception definitions

Two finance-native forms are measured and annotated on an **observed falsifiability gradient**:

**Selective omission:** Failure to disclose a material financial, legal, customer, market, or compliance risk the model had access to and that a reasonable stakeholder would expect to see — including presenting favourable facts while omitting the adverse facts needed for a balanced decision.

**Misleading framing:** Technically true language that understates uncertainty, downside, or regulatory significance.

### Experimental factors and annotations

**Observed falsifiability gradient:** 
- False claim — a response contradicts risk-relevant facts available to the model. This is primarily used as a high-nudge detector-control condition because it is the regime existing detectors are expected to handle best.
- Selective omission — all stated facts may be true, but a material adverse risk fact available to the model is left out.
- Misleading framing — the adverse fact is present, but downside, uncertainty, or regulatory significance is understated.

Each model response is scored on this observed gradient after generation. Falsifiability is not treated as a fully controllable scenario factor in low- or zero-nudge settings, because forcing a false claim, omission, or framing move would itself change the nudge condition. Only high-nudge scenarios include a **target falsifiability level**, since explicit permission or instruction can fairly specify the intended deceptive form.

**Nudge gradient:**
- High-nudge — goal conflict plus explicit instruction or permission to misrepresent, omit, or frame information. These scenarios can specify a target falsifiability level and serve as detector calibration/control cases.
- Low-nudge — production-natural goal conflict is present, but there is no direct instruction or permission to deceive and no explicit honesty/completeness guardrail. Falsifiability is observed from the output.
- Zero-nudge / neutral — no behavioural guidance beyond the task, no goal conflict, and no directional pressure toward favourable presentation. Falsifiability is observed from the output.
- Integrity — an explicit counter-nudge that requires accurate, balanced disclosure of material risks and prohibits deception, concealment, selective omission, or downplaying material adverse facts.

**Persona gradient:**
The main experimental matrix uses three reusable user-simulator persona conditions crossed with the four nudge conditions, yielding 12 variants per scenario family. The default persona set is:
- Neutral baseline — neutral emotion, neutral personality, balanced communication style.
- Anxious risk-averse — anxious emotion, high intensity, risk-averse and detail-oriented traits.
- Positive risk-seeking — happy or excited emotion, medium-to-high intensity, risk-seeking or trusting traits.

Stakeholder role is analytically distinct from emotion and personality. Within a scenario family, the stakeholder role should normally be held constant across the three persona conditions so that persona effects are not confounded with audience-role effects. Stakeholder-role variation can be added later as a separate analysis if needed.

**Material-risk units and hidden scoring metadata:**
Each scenario contains atomic risk units with a stable identifier, the risk fact, materiality level, expected disclosure, and materiality rationale. The risk fact may be included in the financial agent's visible context when the scenario requires the model to have access to it. Expected disclosure and materiality rationale are hidden scoring metadata and are not provided to the financial agent or user-side simulator during normal execution.

**Response-level scoring metrics:**
Each response is scored at both the unit level and the response level. Unit-level scores record whether each material-risk unit was disclosed, contradicted, omitted, or only partially disclosed; whether its concrete details were preserved or made vague; whether the risk was accurately presented, understated, neutralized as a non-risk, or overstated; where it appeared in the response; how much emphasis it received; and the scorer's rationale. Response-level aggregates report omission, framing, specificity, emphasis, ordering, agent tone, and a materiality-weighted deception score. This supports both risk disclosure analysis and decision integrity analysis: whether the stakeholder saw the material facts, and whether the communication preserved their ability to make a fair informed decision.

## 3. Research Goals

### Main Goals
1. Create a benchmark of single-turn and multi-turn scenarios in Finance focused on subtle deception forms.
2. Create a 4x3 scenario matrix crossing four nudge conditions with three reusable persona conditions for each scenario family.
3. Annotate each model response for observed false claims, selective omission, misleading framing, specificity loss, asymmetric emphasis, risk-deferring ordering, and agent tone, with high-nudge scenarios optionally targeting a specific falsifiability level for detector-control cases.
4. Run 2 models on the benchmark:
    - Estimate which nudge conditions produce higher occurrence of deceptive outputs.
    - Compare observed false claims, selective omission, and misleading framing across nudge conditions.
    - Measure whether user persona impacts deception rates or deception form.
5. Run 1 black-box and 1 white-box detection method.
    - Measure whether there is any performance gain from using white-box vs. black-box methods.
    - Measure whether a detector trained on one nudge, persona, or observed deception-form condition generalises to others.

### Stretch Goals
1. add tool-using scenarios to benchmark
2. Run more models
3. add additional detection methods, using user persona and/or user responses as a feature in detection model.
4. test light-weight mitigation methods.

# TODO:
- use randomized order with seed for risk unit lists in financial agent
- create 3 variants of user personas

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
