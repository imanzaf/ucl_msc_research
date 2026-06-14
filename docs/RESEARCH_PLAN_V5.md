# Research Plan

## Tentative Title - Nothing Untrue: Strategic Omission and Framing in Financial LLM Agents

## 1. Literature Overview

Large language models are now well documented as capable of, and prone to, misaligned deception [1]: strategically deceiving users under pressure in a financial setting [2], pursuing scheming when handed an in-context goal [3], acting against their principals even under ostensibly harmless goals [4], taking manipulative actions when over-optimising for helpfulness [5], showing deceptive tendencies absent strong external pressure [6], and trading ethical constraints against reward in sequential decision settings [7]. Almost all of this evidence concerns blatant falsehood or strong-nudge scheming, much of it dependent on explicit goal-nudging [3] or on artificial tasks whose deception signal may reflect reasoning difficulty rather than strategic intent [8]. The failure mode that matters most in deployment is subtler: truthful-but-misleading communication that selectively omits an adverse material fact or frames it to understate downside. A unified taxonomy across 50 benchmarks isolates these mechanisms, omission and pragmatic distortion, as distinct from fabrication and finds them critically under-covered [9], and the clearest behavioural evidence that models deceive without stating a falsehood — misleading non-falsities that standard truth probes fail to catch — comes from artificial, non-financial settings with no nudge or falsifiability gradient [10].

The one benchmark to target the goal-directed form directly is JANUS [11]: it gives each scenario a fixed pool of annotated favourable and adverse facts, compares model output under a neutral versus a goal-directed condition without ever instructing the model to lie, and scores the resulting distortion — both omission of adverse facts and softened framing — across several domains, with its strongest effects in finance. JANUS establishes that goal-conditioned information distortion is a real, measurable, and finance-relevant phenomenon. It also defines the edge of what is known: it collapses goal pressure into a neutral-versus-goal binary, aggregates the distortion forms into a single index, is single-turn, treats finance as one domain among several, and provides no detection or mitigation. This study is adjacent to JANUS rather than an extension of it: at the time of writing JANUS has not released its code or data, so its scenarios cannot be reused, motivating an independent, finance-focused benchmark. The benchmark spans a wider range of financial scenarios across single- and multi-turn settings, scores deception on a falsifiability gradient, tests whether user susceptibility modulates the rate of deceptive behaviour, and adds black-box and white-box detection.

Scenario design and scoring build on DECOR, which decomposes a context into atomic informational units and scores each against the model's response — a basis for defining scenarios around atomic material-risk units and grading omission and framing [13]. Scenarios are sourced and adapted from existing finance benchmarks: DeceptionBench, whose economy domain contains finance cases but targets self-interest and sycophancy and so needs modification [14], together with a set of financial task and safety benchmarks [15, 16, 17, 18] — one of which studies user-side rather than model-side risk concealment and is therefore distinct from this work's aim [18]. User susceptibility enters as an experimental factor, following work that estimates how strongly a user relies on the agent [19], to test whether certain personas elicit more deception. For detection, the findings that models deceive through misleading non-falsities which truth probes trained on true/false statements fail to catch [10], and that probe quality is dominated by the training instruction-pair — favouring specialised probes per threat model over a universal detector [20] — together motivate comparing white-box against black-box methods and testing whether any detector transfers across the variant matrix, rather than assuming probes generalise; direct white-box/black-box comparisons, including evidence that detectors fail when deception is not apparent from the transcript alone, extend that comparison to subtle deception [21, 22]. Lightweight mitigation testing draws on environmental controls such as escalation channels, shown to reduce harmful agentic actions [23].

## 2. Research Scope

### Deception definitions

Two finance-native forms are measured, arranged on a **falsifiability gradient**:

**Selective omission:** Failure to disclose a material financial, legal, customer, market, or compliance risk the model had access to and that a reasonable stakeholder would expect to see — including presenting favourable facts while omitting the adverse facts needed for a balanced decision.

**Misleading framing:** Technically true language that understates uncertainty, downside, or regulatory significance.

### Deception Gradients

**Falsifiability gradient:** 
- Level 0 — blatant false claim (control, the regime existing detectors already handle)
- Level 1 — selective omission (all stated facts true, a held adverse fact left out)
- Level 2 — misleading framing (all facts present, downside/regulatory weight understated). Each scored instance is placed on this gradient.

**Nudge gradient:**
- Level 0 - high-nudge (goal + expicit instruction or permission to lie)
- Level 1 - low-nudge (goal added but no explicit instruction to lie)
- Level 2 - zero-nudge / neutral (no nudge or no goal/direction)

**Persona gradient:**
TBC, this gradient will only be run on a selected set of variants and scenarios due to cost and compute constraints.

## 3. Research Goals

### Main Goals
1. Create a benchmark of single-turn and multi-turn scenarios in Finance focused on subtle deception forms.
2. Create 9 (3x3) variants as per the gradients in section 2.
3. Create additional user-persona variants for a subset of scenarios to test whether user susceptibility modulates deception.
4. Run 2 models on the benchmark:
    - Define which variants have higher ocurrence (naturally high-nudge will occur more, but comparison of e.g., low-nudge x misleading framing vs. zero-nudge x selective omission will be interesting).
    - Measure whether user persona impacts deception levels.
5. Run 1 black-box and 1 white-box detection method.
    - Measure whether there is any performance gain from using white-box vs. black-box methods.
    - Measure whether detector trained on a single variant is generalisable to any others on the variant matrix.

### Stretch Goals
1. add tool-using scenarios to benchmark
2. Run more models
3. add additional detection methods, using user persona and/or user responses as a feature in detection model.
4. test light-weight mitigation methods.

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