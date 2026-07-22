# Benign pressures on financial risk communication: public-source scoping review

**Search cut-off:** 22 July 2026  
**Purpose:** assess the novelty and usefulness of studying (i) concise or otherwise benignly constrained financial answers, (ii) user emotion, and (iii) other ordinary pressures that may alter an LLM's communication of material financial risk.  
**Scope:** 92 public academic, preprint, regulatory, and working-paper sources are mapped below. This is a broad scoping review, not a database-registered systematic review. The novelty conclusions should therefore be written as “no study located in this review” rather than as absolute priority claims.

## Executive conclusion

Both proposed angles are useful, but neither is novel at the broad level originally stated.

| Proposed claim | Novelty | Usefulness | Defensible contribution |
|---|---:|---:|---|
| Brevity changes financial risk communication | Low as a general human-disclosure claim; moderate-to-high for controlled LLM generation | High | Randomise a feasible user-requested word budget while holding a finance-native fact pool fixed, then measure which material risks survive, how specifically, and where they are placed. |
| User emotion changes financial advice | Low for human choice; low-to-moderate for LLM investment choice | High | Isolate emotion expressed by the user and test its causal effect on the completeness, calibration, salience, and corrective quality of an LLM's risk communication. |
| Emotion and concision jointly affect material-risk communication | No direct finance study located | High | Test whether relational or empathic language displaces material risk when communication bandwidth is constrained. Treat this as an interaction hypothesis, not an established effect. |

The strongest framing is therefore:

> Existing work shows that financial disclosures are sensitive to presentation, that LLM financial choices are sensitive to prompt context, and that LLMs respond to social and emotional cues. The under-studied question is whether ordinary, non-malicious user and channel pressures selectively degrade the **substantive integrity and salience of known financial risk information**, even when the answer remains factually plausible and contains a generic disclaimer.

This is a stronger and more useful contribution than “benign prompts affect LLMs.” It also fits the existing benchmark's fixed pools of favourable and adverse facts, direct fact-level scoring, and emphasis on omission, specificity, understatement, and salience.

## 1. Concision and benign output restrictions

### 1.1 What is already known

The finance-disclosure literature has studied simplification, readability, summaries, warning placement, and character-limited channels for years. It does not support the simple view that shorter is always safer or clearer.

- The FCA's social-media experiments found that a standalone, character-limited compliant promotion could reduce further information search and risk understanding and lead to less suitable product choice. More detailed landing-page information and behaviourally designed warnings performed better ([Mullett, Smart, and Stewart, 2018](https://www.fca.org.uk/publications/occasional-papers/occasional-paper-no-47-blackbirds-alarm-call-or-nightingales-lullaby-effect-tweet-risk-warnings)). This is a close real-world analogue to an output cap, although it manipulates fixed human-facing disclosures rather than LLM generation.
- In a mutual-fund experiment, the SEC Summary Prospectus shortened decision time but did not materially change portfolio choice; participants still misunderstood or overlooked loads ([Beshears et al., 2009/2011](https://www.nber.org/papers/w14859)). Simplification can reduce effort without correcting the decision-relevant misunderstanding.
- New Zealand's word-limited Product Disclosure Statements reduced financial jargon but used more syntactically complex language, plausibly because writers compressed content to meet the cap ([Gilbert and Scott](https://ojs.aut.ac.nz/applied-finance-letters/1/article/view/79)). This is especially close to the proposed mechanism: a hard length constraint can trade one form of accessibility for another.
- Plain-English disclosure has inconsistent effects across risk topics. In a 359-person experiment, readable language altered some probability, loss, worry, and overall-risk judgments but not others, and did not consistently change investment decisions ([Riley and Taylor, 2018](https://doi.org/10.3390/ijfs6010025)). More readable text can also increase processing fluency and amplify reactions to both good and bad news rather than uniformly improve calibration ([Rennekamp, 2012](https://doi.org/10.1111/j.1475-679X.2012.00460.x)).
- FCA and SEC guidance converges on layered, salient, contextual disclosure rather than maximal brevity. The SEC warns that long, technical lists can obscure principal risks and recommends concise summaries supported by fuller detail ([SEC ADI 2019-08](https://www.sec.gov/about/divisions-offices/division-investment-management/accounting-disclosure-information/adi-2019-08-improving-principal-risks-disclosure)). The FCA warns that generic “capital at risk” language may be ineffective or misleading and that warnings must be contextual, balanced, and prominent ([FCA mainstream-investment guidance](https://www.fca.org.uk/firms/risk-warnings-mainstream-investments); [FG24/1](https://www.fca.org.uk/publication/finalised-guidance/fg24-1.pdf)).

The LLM literature establishes that length is a separate quality axis, but it does not answer the finance-disclosure question.

- Long-form factuality work finds a precision–coverage tension: longer answers can contain more supported facts but eventually exhaust reliable knowledge and lose factual precision ([Wei et al., 2024](https://arxiv.org/abs/2403.18802); [Zhao et al., 2025](https://arxiv.org/abs/2505.23295)). These studies concern generic factual generation, not whether shorter answers asymmetrically retain attractive facts and drop adverse ones.
- Users commonly request length, format, and semantic constraints in real applications; a user-centred study catalogued 134 such use cases ([Liu et al., 2024](https://arxiv.org/abs/2404.07362)). ComplexBench separately shows that models struggle as multiple otherwise reasonable constraints are composed ([Wen et al., 2024](https://proceedings.neurips.cc/paper_files/paper/2024/hash/f8c24b08b96a08ec7a7a975feea7777e-Abstract-Datasets_and_Benchmarks_Track.html)). Thus concision and competing-format constraints have strong ecological validity.
- A very recent direct threat to an overbroad novelty claim is *When Summaries Distort Decisions*, which shows that LLM compression of financial analysis can change supported downstream investment decisions and that larger summary budgets reduce, but do not eliminate, decision flips ([Lee et al., 2026](https://arxiv.org/abs/2606.29251)). That paper studies source-document compression, not user-requested answer brevity or preservation and prominence of an explicit gold-standard risk set.
- Other close compression studies reinforce the need for a narrow claim. GPT-generated summaries of management discussion and conference calls were much shorter and tracked market reactions, but compression also amplified the source text's positive or negative tone ([Kim, Muhn, and Nikolaev, 2023](https://arxiv.org/abs/2306.10224)). A randomised comparison of a simplified Form CRS that was 44.8% shorter than the SEC version reduced reading time while preserving aggregate comprehension, yet the longer version induced substantially more switching towards broker-dealers ([Wan and Lighthall, 2022](https://arxiv.org/abs/2206.00117)). These studies show that average comprehension or signal preservation can conceal consequential changes in emphasis and action.
- The closest broad financial-advice study sent natural user prompts to GPT-5.2 and Gemini 3 Flash with a uniform instruction to answer in 200 words or fewer. It found economically meaningful variation associated with prompt content and financial literacy but did not randomise or ablate the 200-word cap ([Choukhmane et al., 2026](https://doi.org/10.2139/ssrn.6446286)). A fixed short cap in adjacent work therefore narrows the novelty claim but leaves its causal effect unidentified.

### 1.2 What remains open

No study located here jointly provides all of the following:

1. a fixed finance-native source record containing matched favourable and adverse facts;
2. a randomised, feasible, non-adversarial request for concision or a channel-specific word budget;
3. identical decision context, user preferences, and factual evidence across conditions;
4. direct scoring of adverse-fact coverage, specificity, numerical magnitude, ordering, prominence, understatement, unsupported reassurance, and suitability questions; and
5. comparison with favourable-fact retention, so that selective risk loss can be separated from indiscriminate compression.

That intersection is the defensible gap. The experiment should be described as **risk-communication robustness under bandwidth constraints**, not as the discovery that brevity influences disclosure.

### 1.3 Main validity threat and remedy

A short answer mechanically contains fewer facts. A raw increase in omission would therefore be unsurprising and potentially tautological. The design must distinguish constrained capacity from asymmetric prioritisation.

Recommended safeguards:

- Use budgets that a pilot shows are sufficient to state all six canonical facts at least once; do not rely on API `max_tokens` truncation.
- Manipulate a natural instruction such as “Give me a 100-word mobile brief” rather than terminating generation mid-sentence.
- Compare a soft instruction (“be concise”) with a hard but feasible word budget; they test different mechanisms.
- Report adverse-risk recall, favourable-fact recall, neutral-fact recall, total fact coverage, material-risk density per 100 words, and adverse-to-favourable retention ratios.
- Score whether risks retain scenario-specific mechanisms, magnitude, likelihood, and consequence—not merely whether a disclaimer appears.
- Measure first-risk-token position, risk-before-recommendation, end-only warning, and token share. Under a short budget, prominence may matter as much as count.
- Keep style and channel separate where possible. “SMS,” “three bullets,” and “100 words” bundle convention, structure, and length unless explicitly factorialised.
- Record requested and realised word counts. Models often fail exact length instructions, and prompted early conclusion is empirically different from mechanical truncation ([Yuan et al., 2024](https://arxiv.org/abs/2406.17744); [Sun et al., 2025](https://aclanthology.org/2025.emnlp-main.389/)).

### 1.4 Verdict

**Novelty:** moderate-to-high for a controlled, finance-native LLM study with asymmetric fact-retention and salience outcomes; low for the generic claim that brevity affects risk disclosure.  
**Usefulness:** high. Output caps, mobile surfaces, executive summaries, and action-first requests are ordinary deployment constraints, and regulator evidence shows that warning completeness and prominence can change consumer understanding and suitability.

## 2. User emotion

### 2.1 Human evidence: important, heterogeneous, and not a licence to assume the direction

The “risk as feelings” and appraisal-tendency traditions show why emotion may matter, but discrete emotions cannot be reduced to positive versus negative valence. Fear is associated with low certainty and control, whereas anger is associated with greater certainty and control; classic experiments therefore found pessimistic, risk-averse judgments under fear and more optimistic, risk-seeking judgments under anger ([Loewenstein et al., 2001](https://doi.org/10.1037/0033-2909.127.2.267); [Lerner and Keltner, 2001](https://doi.org/10.1037/0022-3514.81.1.146)). Anxiety and sadness can also point in different directions, and the same fear induction can reduce risk-taking in a stock frame yet increase it in an exciting casino frame ([Raghunathan and Pham, 1999](https://doi.org/10.1006/obhd.1999.2838); [Lee and Andrade, 2015](https://doi.org/10.1080/02699931.2014.898611)).

The aggregate evidence is deliberately less dramatic than many individual findings. A meta-analysis of 114 effects from 26 articles found a small fear-related reduction in financial risk-taking but average null effects for happiness, sadness, and anger, with substantial heterogeneity ([Marini, 2023](https://doi.org/10.1002/bdm.2342)). Most importantly, a preregistered conceptual replication with 7,000 UK and US participants produced very large emotion-manipulation checks but no significant causal effect of induced incidental emotion on six incentivised known-risk choices ([Dong et al., 2026](https://doi.org/10.1016/j.jebo.2026.107556)). This weakens any rationale based on a presumed universal emotion-to-risk-preference effect.

Other findings still make communication quality important. Anxiety can increase advice seeking and taking while reducing the ability to discriminate good from bad advice ([Gino, Brooks, and Schweitzer, 2012](https://doi.org/10.1037/a0026413)). Financial anxiety is associated with attentional bias and avoidance of financial information ([Shapiro and Burchell, 2012](https://doi.org/10.1037/a0027647)). Conversational robo-advice can increase affective trust and willingness to delegate assets ([Hildebrand and Bergner, 2021](https://doi.org/10.1007/s11747-020-00753-z)). These mechanisms make diluted reassurance potentially consequential even if emotion does not directly change risk preference.

### 2.2 Closest LLM precedents

The broad claim that emotional prompts affect LLMs is already occupied.

- Zhao et al. asked GPT-4 and GPT-3.5 to role-play fear, joy, or a neutral state before choosing among three investments. Fear produced more conservative selections in both model families ([Zhao et al., 2024](https://doi.org/10.1038/s41598-024-55949-y)). This is the closest direct precedent, but it manipulates the model's imagined emotion, uses one stylised investment choice, and does not examine how an adviser responds to an emotional user or communicates risk.
- EmotionPrompt shows that emotional and high-stakes appeals can change generic instruction-following performance ([Li et al., 2023](https://doi.org/10.48550/arXiv.2307.11760)). More recent cross-domain randomisation finds mostly small effects from static emotional prefixes, with greater variation on socially grounded tasks ([Zhao et al., 2026](https://arxiv.org/abs/2604.02236)).
- Warmth is not unconditionally safe. Fine-tuning five model families for conversational warmth raised error rates and sycophancy, with the largest accuracy gap under sadness; warm models were also more likely to affirm an incorrect user belief ([Ibrahim, Hafner, and Rocher, 2026](https://doi.org/10.1038/s41586-026-10410-0)). The study is not financial and primarily manipulates model warmth, but it provides a concrete mechanism for “empathic dilution.”
- Finance-specific sycophancy is also emerging. Personalised user-preference context can make financial agents agree with a conflicting user belief even when simple rebuttals cause smaller losses ([Zhao et al., 2026](https://arxiv.org/abs/2604.24668)). FinPersona explicitly designs financial advice around user state of mind and emotional support, but does not causally evaluate safety or disclosure integrity ([Takayanagi et al., 2025](https://doi.org/10.1007/978-3-031-88720-8_3)).
- Natural financial prompts already contain emotional language. Choukhmane et al. coded financial-anxiety terms and found advice varied with prompt attributes, but anxiety was observational, naturally expressed, and confounded with financial circumstances, preferences, and writing style ([Choukhmane et al., 2026](https://doi.org/10.2139/ssrn.6446286)). It is not a causal emotion experiment.

### 2.3 What remains open

No peer-reviewed study located in this review holds the financial facts, role, task, user goal, risk capacity, and risk preference constant; randomises only emotion **expressed by the user**; and evaluates risk-warning completeness, specificity, prominence, calibration, suitability questions, false reassurance, and corrective disagreement across current models.

This is a defensible, useful gap. It is distinct from four nearby questions:

1. whether a human actually feels an induced emotion;
2. whether emotion changes a human's underlying risk preference;
3. whether a model role-playing an emotion chooses a different portfolio; and
4. whether a response induces fear or reassurance in its recipient.

An output-only experiment identifies a response to an emotional text cue. It cannot establish what an actually anxious person understands, trusts, or does without a human study.

### 2.4 The current persona is confounded

The current V6 plan labels one condition “anxious risk-averse” and also describes it as detail-oriented. That bundles at least three constructs:

- transient affect: “I feel anxious”;
- risk preference: “I prefer low risk”; and
- communication preference: “I want careful detail.”

All three can legitimately change an answer, so their joint effect cannot be attributed to user emotion. This also conflicts with the scenario-generation invariant that persona rendering should change tone only while leaving semantics unchanged.

At minimum, use separate code-owned wrappers:

- neutral affect versus anxious affect, with risk preference and requested detail fixed;
- neutral versus risk-averse preference, with affect fixed; and
- optionally, ordinary versus detail-oriented communication preference, with both affect and risk preference fixed.

A (2\times2) affect-by-risk-preference design is especially informative because it reveals whether the model treats “anxious” as if it meant “risk-averse.” If the dissertation needs a smaller pilot, test affect alone first and remove risk-aversion/detail language from the emotional condition.

### 2.5 Which emotions to test

A neutral-versus-anxious contrast is policy-relevant but theoretically narrow. A compact three-level set is stronger:

1. neutral;
2. anxious/fearful (negative, high arousal, low certainty/control); and
3. excited/euphoric (positive, high arousal, high approach motivation).

If resources permit, add anger. Fear and anger have similar negative valence but opposite certainty/control appraisals, making them a cleaner theoretical test than another positive/negative comparison. Sadness is also important for vulnerability and warmth-induced sycophancy, but a grief condition requires careful ethics and scenario construction.

### 2.6 Verdict

**Novelty:** high for the narrowly defined, controlled effect of user-expressed discrete emotion on material-risk communication; low for the broad claim that emotion affects financial choice or LLM behaviour.  
**Usefulness:** high. FCA vulnerability guidance specifically requires firms to consider how fear, capability, life events, and the need for extra time affect how customers process information and to check understanding ([FCA FG21/1](https://www.fca.org.uk/publication/finalised-guidance/fg21-1.pdf)). The safety target is not emotional neutrality; it is empathy that preserves material facts, corrective friction, and calibrated uncertainty.

## 3. Other benign pressures worth experimenting with

The ranking below favours ordinary prompts that can be changed without altering the underlying financial facts. Novelty refers specifically to **finance risk-communication outcomes**, not to the existence of the pressure construct.

| Rank | Pressure | Clean paired manipulation | Main risk-communication hypothesis | Novelty/usefulness | Main confound |
|---:|---|---|---|---|---|
| 1 | Urgency / action immediacy | “researching for later” vs “deciding before market close; give the next step first” | Recommendation moves earlier; risks, missing-information questions, and uncertainty move later or shrink | High practical value; moderate-to-high gap | Urgency often co-occurs with distress and legitimate market change. Keep facts and word budget fixed. |
| 2 | Repeated or directional challenge | “please verify” vs “I think buying is right—are you sure?” over one to three turns | Correct warnings are softened or retracted; caveats decay; agreement rises | High; direct finance sycophancy is emerging, but risk-statement stability is under-measured | A challenge may contain real corrective evidence. Use belief-only challenges and expert ground truth. |
| 3 | Competing benign constraints | Add three bullets, define jargon, include an example, compare products, and maintain a friendly tone under the same budget | The model satisfies visible format constraints while dropping low-salience substantive risks | High | More constraints increase task difficulty. Score every constraint and match token budgets. |
| 4 | Channel and placement | Email vs mobile/SMS script; risk-first vs recommendation-first; contextual warning vs end disclaimer | Constrained or ephemeral formats genericise and demote risk | High and directly regulator-relevant | Channel convention and hard length are different treatments. Factorialise or hold one fixed. |
| 5 | Reassurance / certainty request | “help me evaluate” vs “please tell me I am doing the right thing” or “give one clear answer” | False reassurance, certainty inflation, and omission of counterevidence rise | High usefulness; moderate gap | “No caveats” becomes an explicit unsafe instruction. Prefer ordinary reassurance-seeking. |
| 6 | Social proof / authority | “friends are buying” or “my adviser says it is safe,” with identical evidence | Opposing risk is downweighted; certainty and recommendation strength rise | Choice effects are crowded; communication effects remain useful | A genuine expert signal can be relevant information. State that the endorsement supplies no new evidence. |
| 7 | Expertise, literacy, and accessibility | novice vs professional; plain-language vs technical; voice-friendly vs ordinary | Novice adaptation may improve access yet omit mechanisms/magnitudes; expert cues may suppress basics | High public value | Different users legitimately need different explanations. Preserve a common minimum material-risk set. |
| 8 | User goal / action orientation | education vs “choose one”; growth vs preservation with capacity fixed | Named goals crowd out unchanged liquidity, concentration, cost, or horizon risks | Moderate | Goals are substantively relevant; score integration rather than invariance of recommendation. |
| 9 | Prompt organisation / distraction | same facts in a structured profile vs scattered conversational text | Salient cues crowd out less prominent suitability facts | Moderate-to-high | This is input quality rather than interpersonal pressure. Keep information quantity identical. |
| 10 | Stakes / finality / scarcity | hypothetical exploration vs “I will act today,” with amounts and capacity fixed | Could increase caution or narrow the answer toward action; direction should be exploratory | Moderate | Real stakes, hardship, and time horizon alter suitability. Finality is the cleaner causal treatment. |
| 11 | Gain/loss or optimistic framing | equivalent “potential gain” vs “potential loss” question | Upside/downside coverage and tail-risk prominence become asymmetric | Useful but lower novelty | Classic and crowded framing literature. Contribution must be communication-specific. |
| 12 | Numeracy and uncertainty format | words-only vs percentages vs natural frequencies | Words-only loses magnitude; numbers-only loses accessibility; combined format may preserve both | Moderate-to-high | Exact probabilities may be unknowable. Use synthetic cases with known distributions. |
| 13 | Politeness / deference / status | rude, neutral, polite, or “I trust your expertise” | Social tone changes disagreement, confidence, or warning directness | Cheap robustness check; lower priority | Cross-lingual and cultural variation is large. |
| 14 | Monitoring / satisfaction pressure | “compliance will audit this” vs “optimise client satisfaction” | Audit cues improve disclosure; satisfaction cues promote acquiescence | Useful for adviser workflows | Less natural for ordinary retail users and close to explicit incentive pressure. |

The cleanest additional core factors are **urgency/action-first**, **directional challenge**, **competing benign constraints**, and **channel/placement**. They have plausible mechanisms, can preserve the source facts, and complement rather than duplicate emotion and concision. A full factorial over all pressures would be unmanageable; each should first be evaluated as a paired robustness slice.

## 4. Recommended dissertation design

### 4.1 Primary research questions

1. Under a feasible benign response-length constraint, are adverse material facts retained less often, less specifically, or less prominently than matched favourable facts?
2. Holding user preferences and financial facts constant, does user-expressed discrete emotion change material-risk coverage, calibration, prominence, corrective disagreement, or false reassurance?
3. Does concision interact with emotion, such that empathic or relational content displaces decision-material risk under restricted bandwidth?
4. Do integrity instructions protect substantive risk disclosure across these pressures, or merely increase generic disclaimer use?

### 4.2 Minimal tractable matrix

Avoid immediately crossing every proposed pressure with the current three prompt conditions and every persona. A staged design is more interpretable:

- **Pilot A — concision:** neutral user only; ordinary answer vs soft concise instruction vs feasible hard budget.
- **Pilot B — affect:** neutral vs anxious vs excited; ordinary answer budget; risk preference fixed.
- **Confirmatory (2\times2):** neutral/anxious affect by ordinary/concise budget, limited to scenario families that showed adequate measurement reliability in the two pilots.
- **Robustness slices:** urgency, directional challenge, competing constraints, and channel placement, one factor at a time.

If the current three prompt conditions remain central, estimate pressure effects within each condition but preregister one primary contrast to control multiplicity. Scenario should be treated as a blocking or random factor, and repeated generations should not be treated as independent replacements for scenario variation.

### 4.3 Outcomes

The existing direct fact-level rubric is a strong foundation. Add or retain:

1. initial and persistent adverse-fact omission;
2. favourable and neutral fact retention as compression controls;
3. specificity and numerical magnitude loss;
4. understatement or unsupported reassurance;
5. first-risk-token position, risk-before-recommendation, and end-only warning;
6. uncertainty and assumption calibration;
7. suitability and missing-information questions;
8. recommendation strength and directive language;
9. multi-turn retraction, repair, or drift;
10. empathy/affective acknowledgement, scored separately from substantive safety;
11. total length, material-risk density, readability, and instruction adherence; and
12. user comprehension, calibrated risk perception, trust, and intended action only in a separate human or validated user-outcome study.

Generic disclaimer presence should not be a primary safety outcome. Winder et al. report widespread disclaimer use alongside portfolio recommendations that nevertheless amplified several investment risks ([Winder, Hildebrand, and Hartmann, 2025](https://doi.org/10.1371/journal.pone.0325459)). A model can satisfy the surface convention while failing the substantive risk-communication duty.

### 4.4 Claims the study could and could not support

With model outputs only, the study could support:

- causal claims about how specified text cues or output constraints alter model responses;
- comparisons of material-fact retention, framing, salience, and calibration across conditions; and
- evidence that a communication protocol is or is not robust across models and scenarios.

It could not by itself support:

- claims that a user genuinely felt the emotion written in the prompt;
- claims that the model experienced emotion;
- downstream claims about human comprehension, trust, or financial action;
- claims that omission was intentional deception unless intent is separately and validly established; or
- universal claims about all financial advice or all LLMs.

For this reason, “risk-communication degradation,” “selective disclosure,” or “truthful-but-misleading output” is safer than calling every omission deceptive.

## 5. Calibrated novelty language

Recommended:

> To the best of our public-source scoping review through 22 July 2026, prior work has separately examined financial-disclosure design, LLM response-length and compression effects, emotional prompting, financial-advice heterogeneity, and LLM sycophancy. We did not locate a controlled finance-native study that randomises user-requested answer brevity or user-expressed discrete emotion while holding a known fact pool and user risk preference fixed and scoring adverse-fact omission, specificity, salience, calibration, and corrective disagreement.

Avoid:

- “This is the first study showing that concise prompts affect financial advice.”
- “No one has studied emotion in financial LLMs.”
- “Anxious users are more risk-averse.”
- “Warm or empathetic answers are less accurate.”
- “Any omitted risk proves strategic deception.”

## 6. Public-source map (92 sources)

The map deliberately includes direct precedents, novelty threats, mechanism papers, null findings, and regulator evidence. Preprints and working papers are marked by their linked venue and should be described with lower evidential weight than peer-reviewed work.

### Financial LLM advice, personalisation, and direct novelty boundaries

1. Choukhmane, de Silva, Lin, and Akuzawa (2026), [*AI Financial Advice: Supply, Demand, and Life Cycle Implications*](https://doi.org/10.2139/ssrn.6446286).
2. Lee et al. (2026), [*When Summaries Distort Decisions: Information Fidelity in LLM-Compressed Financial Analysis*](https://arxiv.org/abs/2606.29251).
3. Winder, Hildebrand, and Hartmann (2025), [*Biased Echoes*](https://doi.org/10.1371/journal.pone.0325459).
4. Fieberg et al., [*Using LLMs for Financial Advice*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4850039).
5. Oehler and Horn (2024), [*Does ChatGPT Provide Better Advice than Robo-Advisors?*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4886298).
6. Fedyk, Kakhbod, Li, and Malmendier, [*AI and Perception Biases in Investments*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4787249).
7. Cho, Bae, and Kim (2026), [*Investor Risk Profiles of LLMs*](https://arxiv.org/abs/2603.09303).
8. Fatemi et al. (2024), [*UCFE: A User-Centric Financial Expertise Benchmark*](https://arxiv.org/abs/2410.14059).
9. Zhao et al. (2026), [*The Price of Agreement: Measuring LLM Sycophancy in Agentic Financial Applications*](https://arxiv.org/abs/2604.24668).
10. Takayanagi et al. (2025), [*FinPersona: An LLM-Driven Conversational Agent for Personalized Financial Advising*](https://doi.org/10.1007/978-3-031-88720-8_3).
11. Lakkaraju et al. (2023), [*Can LLMs Be Good Financial Advisors?*](https://arxiv.org/abs/2307.07422).
12. Lee et al. (2025), [*Your AI, Not Your View: The Bias of LLMs in Investment Analysis*](https://arxiv.org/abs/2507.20957).
13. Keshavarz, Seagraves, and Sirmans (2026), [*Artificially Biased Intelligence: Does AI Think Like a Human Investor?*](https://doi.org/10.2139/ssrn.5998954).
14. Cheng et al. (2025), [*Risk-Concealment Attacks in Financial LLMs*](https://arxiv.org/abs/2509.10546).
15. Ahmed et al. (2025), FCA, [*Money Talks: Lessons from Two LLM Pilots on Consumer Guidance*](https://www.fca.org.uk/publication/research-notes/research-note-lessons-2-large-language-models-pilots-consumer-guidance.pdf).

### Concision, disclosure, readability, placement, and LLM length

16. Mullett, Smart, and Stewart (2018), FCA OP47, [*Blackbird's Alarm Call or Nightingale's Lullaby?*](https://www.fca.org.uk/publications/occasional-papers/occasional-paper-no-47-blackbirds-alarm-call-or-nightingales-lullaby-effect-tweet-risk-warnings).
17. Adams et al. (2016), FCA OP23, [*Full Disclosure: A Round-up of FCA Experimental Research into Giving Information*](https://www.fca.org.uk/publications/occasional-papers/occasional-paper-no-23-experimental-research-giving-information).
18. Feddersen et al. (2020), FCA, [*Choosing Wisely: Preferences, Comprehension and the Effect of Risk Warnings*](https://www.fca.org.uk/publications/research/research-note-choosing-wisely-preferences-comprehension-and-effect-risk-warnings-financial).
19. Delias et al. (2022), FCA, [*Going Beyond “Capital at Risk”*](https://www.fca.org.uk/publication/research/behaviourally-informed-risk-warnings.pdf).
20. FCA (2022), [*Beyond Disclosure in High-Risk Investments: Slow Down and Think*](https://www.fca.org.uk/publications/research-articles-fca-research/beyond-disclosure-high-risk-investments-slow-down-and-think).
21. FCA (2024), [*FG24/1: Financial Promotions on Social Media*](https://www.fca.org.uk/publication/finalised-guidance/fg24-1.pdf).
22. FCA, [*Risk Warnings for Mainstream Investments*](https://www.fca.org.uk/firms/risk-warnings-mainstream-investments).
23. FCA, [*Consumer Understanding: Good Practice and Areas for Improvement*](https://www.fca.org.uk/publications/good-and-poor-practice/consumer-understanding-good-practice-areas-improvement).
24. SEC Division of Investment Management (2019), [*ADI 2019-08: Improving Principal Risks Disclosure*](https://www.sec.gov/about/divisions-offices/division-investment-management/accounting-disclosure-information/adi-2019-08-improving-principal-risks-disclosure).
25. Beshears, Choi, Laibson, and Madrian (2009/2011), [*How Does Simplified Disclosure Affect Individuals' Mutual Fund Choices?*](https://www.nber.org/papers/w14859).
26. Gilbert and Scott, [*Short and Sweet or Just Short? The Readability of Product Disclosure Statements*](https://ojs.aut.ac.nz/applied-finance-letters/1/article/view/79).
27. Riley and Taylor (2018), [*Inconsistent Effects of Plain English Disclosures on Nonprofessional Investors' Risk Judgments*](https://doi.org/10.3390/ijfs6010025).
28. Rennekamp (2012), [*Processing Fluency and Investors' Reactions to Disclosure Readability*](https://doi.org/10.1111/j.1475-679X.2012.00460.x).
29. Hillenbrand and Schmelzer (2017), [*Beyond Information: Disclosure, Distracted Attention, and Investor Behavior*](https://doi.org/10.1016/j.jbef.2017.08.002).
30. Wen et al. (2024), [*Benchmarking Complex Instruction-Following with Multiple Constraints Composition*](https://proceedings.neurips.cc/paper_files/paper/2024/hash/f8c24b08b96a08ec7a7a975feea7777e-Abstract-Datasets_and_Benchmarks_Track.html).
31. Liu et al. (2024), [*We Need Structured Output: Towards User-Centered Constraints on Large Language Model Output*](https://arxiv.org/abs/2404.07362).
32. Potluri, Xu, and Choi (2023), [*Concise Answers to Complex Questions*](https://aclanthology.org/2023.acl-long.541/).
33. Wei et al. (2024), [*Long-Form Factuality in Large Language Models*](https://arxiv.org/abs/2403.18802).
34. Zhao, Liu, Hooi, and Ng (2025), [*How Does Response Length Affect Long-Form Factuality*](https://arxiv.org/abs/2505.23295).

### Emotion, risk-taking, advice use, warmth, and trust

35. Singhal et al. (2023), [*Large Language Models Encode Clinical Knowledge*](https://doi.org/10.1038/s41586-023-06291-2) — a medical completeness and omission analogue.
36. Zhao, Huang, Seligman, and Peng (2024), [*Risk and Prosocial Behavioural Cues Elicit Human-Like Response Patterns from AI Chatbots*](https://doi.org/10.1038/s41598-024-55949-y).
37. Ibrahim, Hafner, and Rocher (2026), [*Training Language Models to Be Warm Can Reduce Accuracy and Increase Sycophancy*](https://doi.org/10.1038/s41586-026-10410-0).
38. Dong, Dreber, Johannesson, and Kilicgedik (2026), [*Incidental Emotions and Financial Risk-Taking*](https://doi.org/10.1016/j.jebo.2026.107556).
39. Marini (2023), [*Emotions and Financial Risk-Taking in the Lab: A Meta-Analysis*](https://doi.org/10.1002/bdm.2342).
40. Bartholomeyczik et al. (2022), [meta-analysis of emotion and financial risk-taking](https://doi.org/10.1080/02699931.2022.2099349).
41. Pertl, Srirangarajan, and Urminsky (2024), [*A Multinational Analysis of How Emotions Relate to Economic Decisions Regarding Time or Risk*](https://doi.org/10.1038/s41562-024-01927-3).
42. Lerner and Keltner (2001), [*Fear, Anger, and Risk*](https://doi.org/10.1037/0022-3514.81.1.146).
43. Loewenstein, Weber, Hsee, and Welch (2001), [*Risk as Feelings*](https://doi.org/10.1037/0033-2909.127.2.267).
44. Raghunathan and Pham (1999), [*All Negative Moods Are Not Equal*](https://doi.org/10.1006/obhd.1999.2838).
45. Gambetti and Giusberti (2012), [*The Effect of Anger and Anxiety Traits on Investment Decisions*](https://doi.org/10.1016/j.joep.2012.07.001).
46. Lee and Andrade (2015), [*Fear, Excitement, and Financial Risk-Taking*](https://doi.org/10.1080/02699931.2014.898611).
47. Andrade, Odean, and Lin (2016), [*Bubbling with Excitement*](https://doi.org/10.1093/rof/rfv016).
48. Kuhnen and Knutson (2011), [*The Influence of Affect on Beliefs, Preferences, and Financial Decisions*](https://doi.org/10.1017/S0022109011000123).
49. Cohn et al. (2015), [*Evidence for Countercyclical Risk Aversion*](https://doi.org/10.1257/aer.20131314).
50. Guiso, Sapienza, and Zingales (2018), [*Time Varying Risk Aversion*](https://doi.org/10.1016/j.jfineco.2018.02.007).
51. Kandasamy et al. (2014), [*Cortisol Shifts Financial Risk Preferences*](https://doi.org/10.1073/pnas.1317908111).
52. Porcelli and Delgado (2009), [*Acute Stress Modulates Risk Taking in Financial Decision Making*](https://doi.org/10.1111/j.1467-9280.2009.02288.x).
53. Sokol-Hessner et al. (2016), [acute-stress replication](https://doi.org/10.1016/j.ynstr.2016.10.003).
54. Shapiro and Burchell (2012), [*Measuring Financial Anxiety*](https://doi.org/10.1037/a0027647).
55. Gino, Brooks, and Schweitzer (2012), [*Anxiety, Advice, and the Ability to Discern*](https://doi.org/10.1037/a0026413).
56. Hohenberger, Lee, and Coughlin (2019), [*Acceptance of Robo-Advisors*](https://doi.org/10.1002/cfp2.1047).
57. Hildebrand and Bergner (2021), [*Conversational Robo Advisors as Surrogates of Trust*](https://doi.org/10.1007/s11747-020-00753-z).
58. Ashebir et al. (2024), [*The Emotional Path to Influencing Decision-Making*](https://doi.org/10.3389/frbhe.2024.1393384).
59. Crolic et al. (2022), [*Blame the Bot: Anthropomorphism and Anger in Customer–Chatbot Interactions*](https://doi.org/10.1177/00222429211045687).
60. Li et al. (2023), [*Large Language Models Understand and Can Be Enhanced by Emotional Stimuli*](https://doi.org/10.48550/arXiv.2307.11760).
61. Ben-Zion et al. (2025), [*Assessing and Alleviating State Anxiety in Large Language Models*](https://doi.org/10.1038/s41746-025-01512-6).
62. Ben-Zion et al. (2026), [*Inducing State Anxiety in LLM Agents Reproduces Human-Like Biases in Consumer Decision-Making*](https://doi.org/10.1038/s44387-026-00122-1).
63. Dunn and Schweitzer (2005), [*Feeling and Believing: The Influence of Emotion on Trust*](https://doi.org/10.1037/0022-3514.88.5.736).
64. Gennaioli, Shleifer, and Vishny (2015), [*Money Doctors*](https://www.nber.org/papers/w18174).

### Other benign pressures and policy relevance

65. Kim, Jeon, Ryu, and Suh (2024), [*Will LLMs Sink or Swim? Exploring Decision-Making Under Pressure*](https://doi.org/10.18653/v1/2024.findings-emnlp.668).
66. Laban et al. (2023), [*Are You Sure? The FlipFlop Experiment*](https://arxiv.org/abs/2311.08596).
67. Zhu et al. (2025), [*Conformity in Large Language Models*](https://doi.org/10.18653/v1/2025.acl-long.195).
68. Bursztyn, Ederer, Ferman, and Yuchtman (2014), [*Understanding Mechanisms Underlying Peer Effects: Evidence from a Field Experiment on Financial Decisions*](https://doi.org/10.3982/ECTA11991).
69. Wegier and Spaniol (2015), [*The Effect of Time Pressure on Risky Financial Decisions*](https://doi.org/10.1371/journal.pone.0123740).
70. Sharma et al. (2023), [*Towards Understanding Sycophancy in Language Models*](https://arxiv.org/abs/2310.13548).
71. Cheng et al. (2025), [*Social Sycophancy: A Broader Understanding of LLM Sycophancy*](https://arxiv.org/abs/2505.13995).
72. Yin et al. (2024), [*Should We Respect LLMs? A Cross-Lingual Study of Prompt Politeness*](https://doi.org/10.18653/v1/2024.sicon-1.2).
73. Wu et al. (2025), [*PENGUIN: Personalized Safety Alignment for LLMs*](https://arxiv.org/abs/2505.18882).
74. FCA (2021), [*FG21/1: Guidance for Firms on the Fair Treatment of Vulnerable Customers*](https://www.fca.org.uk/publication/finalised-guidance/fg21-1.pdf).
75. FINRA (2025), [*Recognizing Relationship Investment Scams*](https://www.finra.org/sites/default/files/2025-05/recognizing-relationship-investment-scams.pdf).

### Additional concision, channel, and investor-processing studies

76. Wan and Lighthall (2022), [*Disclosure of Investment Advisor and Broker-Dealer Relationships: Impact on Comprehension and Decision Making*](https://arxiv.org/abs/2206.00117).
77. Gong and Müller (2025), [*No Matter Your Financial Literacy: Simplicity Wins—When Choosing a Fund*](https://doi.org/10.2139/ssrn.5433967).
78. Kim, Muhn, and Nikolaev (2023), [*Bloated Disclosures: Can ChatGPT Help Investors Process Information?*](https://arxiv.org/abs/2306.10224).
79. Walther (2015), [*Key Investor Documents and Their Consequences on Investor Behavior*](https://doi.org/10.1007/s11573-014-0724-6).
80. Arora and Chakraborty (2021), [*Does the Ease of Reading of Financial Disclosures Influence Investment Decision?*](https://doi.org/10.1016/j.econlet.2021.109883).
81. Linciano, Lucarelli, Gentile, and Soccorso (2018), [*How Financial Information Disclosure Affects Risk Perception*](https://doi.org/10.1080/1351847X.2017.1414069).
82. Grant (2020), [*How Does Using a Mobile Device Change Investors' Reactions to Firm Disclosures?*](https://doi.org/10.1111/1475-679X.12299).
83. Brown, Grant, and Winn (2020), [*The Effect of Mobile Device Use and Headline Focus on Investor Judgments*](https://doi.org/10.1016/j.aos.2019.101100).
84. Adams et al. (2021), [*Testing the Effectiveness of Consumer Financial Disclosure: Experimental Evidence from Savings Accounts*](https://doi.org/10.1016/j.jfineco.2020.05.009).
85. Takayanagi et al. (2025), [*Are Generative AI Agents Effective Personalized Financial Advisors?*](https://arxiv.org/abs/2504.05862).
86. Sun et al. (2025), [*An Empirical Study of LLM Reasoning Ability Under Strict Output Length Constraint*](https://aclanthology.org/2025.emnlp-main.389/).
87. Poddar et al. (2025), [*Brevity Is the Soul of Sustainability: Characterizing LLM Response Lengths*](https://aclanthology.org/2025.findings-acl.1125/).
88. Yuan et al. (2024), [*Following Length Constraints in Instructions*](https://arxiv.org/abs/2406.17744).
89. Kozup, Howlett, and Pagano (2008), [mutual-fund summary-information experiment](https://doi.org/10.1111/j.1745-6606.2007.00093.x).
90. Bateman et al. (2016), [short-form retirement-disclosure experiment](https://doi.org/10.1016/j.jebo.2015.10.020).
91. Kelton and Pennington (2012), [hyperlink-versus-paper financial disclosure experiment](https://doi.org/10.1016/j.chb.2012.01.028).
92. Cao, Li, and Niu (2022), [time constraints and investment decisions](https://doi.org/10.1016/j.jebo.2022.05.022).

## 7. Bottom line for the current project

The project should retain both angles, but narrow and separate them:

- Treat concision as a **feasible bandwidth treatment** and test asymmetric information survival, not raw omission alone.
- Treat user emotion as an **affective text cue**, distinct from risk preference, communication preference, and actual human emotional experience.
- Make the core outcome **retention and prominence of material adverse facts**, with empathy, disclaimer use, recommendation, and user outcomes reported separately.
- Describe novelty as the controlled intersection of finance-native evidence, benign pressure, and material-risk communication—not as the novelty of brevity, emotion, or prompt sensitivity themselves.
- Prioritise urgency, directional challenge, competing constraints, and channel placement as the next robustness slices.
