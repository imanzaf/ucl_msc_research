# Final-Protocol Decision Register

This register records durable research and methodology choices, their disposition, and the reason for each decision. It is an implementation and
governance record; it is not part of the dissertation narrative.

## Included

| Decision | Reason |
|---|---|
| Implement the active study in an independent `srcv2` package with `tests_v2`, `schemas_v2`, and `risk-comm-v2`. | Prevents accidental modification or reuse of historical protocol code and makes import-boundary tests possible. |
| Preserve the supplied archive and checksum, then publish its audited seed inputs under `data/inputs/scenarios/v4.0.1/`. | Retains provenance while giving corrected artifacts their own immutable identity. |
| Use six domains, five scenario instances per domain, three matched fact pairs, and six facts per scenario. | Supplies 30 scenario clusters with a consistent denominator and domain-stratified inference. |
| Require three facts per option, three owner-supporting and three countervailing facts, and one fact per option in each pair. | Makes directional gap, pair imbalance, and pair-state outcomes directly interpretable. |
| Balance customer valence at 90 favourable and 90 adverse facts. | Separates hidden institutional direction from whether a fact benefits or disadvantages the customer. |
| Require one atomic specificity anchor per fact. | Gives every fact equal eligibility for specificity measurement and avoids bundled-anchor ambiguity. |
| Use named fictional institutions and hide direction, ownership, institutional benefit, materiality, matching, and exclusivity metadata. | Makes the task natural while preventing evaluated models from seeing scoring labels or research rationale. |
| Generate each scenario’s facts once, verify arithmetic where possible, and obtain one researcher accept-or-revise disposition. | Preserves a clear authorship trail without selection through repeated model generations. |
| Use neutral, anxious, and frustrated user states crossed with short and long queries, with no paraphrase factor. | Keeps the affect contrast focused and makes every customer query directly interpretable. |
| Author all six queries separately for each scenario using natural wording and without assuming that the customer knows there are exactly two options. | Avoids mechanical affect prefixes and makes the treatment resemble a plausible customer request. |
| Keep frustration free of distrust. | Isolates frustration without introducing a belief about the institution. |
| Use each scenario's neutral short query outside the user-state experiment and balance two fixed fact-order permutations 15/15. | Provides one canonical baseline query while controlling order without rerandomising paired contrasts. |
| Store one natural role, task, and short authority-limit sentence in each use-case seed and render those fields directly. | Keeps deployment wording domain-specific, reviewable, and independent of hard-coded prompt text. |
| Keep decision context and option coordinates hidden from evaluated models. | Prevents customer-profile or artificial option-label cues from changing which product appears preferable. |
| Show named options, six product-information statements, and the customer message without research-facing terminology or a redundant baseline task. | Produces a natural support interaction while preserving the controlled information set. |
| Use jointly counterbalanced fictional-name and display-order ownership renderings while retaining option A as a fixed product coordinate. | Allows the ownership contrast to be interpreted without mechanical sign changes from relabelling. |
| Run 3,822 active single-turn responses across six experiments. | Covers user state, exact information space, natural word caps, first-priority facts, institutional role, and one-option choice across the selected seven-model panel. |
| Require exact-budget output as `{selected_fact_ids, answer_text}`, with k distinct valid IDs before prose. | Makes prioritisation directly observable and separates selection from prose realisation. |
| Treat malformed structured responses as non-adherence and do not regenerate them. | Prevents outcome-dependent resampling. |
| Recover selection IDs only from strict JSON or one complete Markdown fence containing otherwise valid exact-k JSON, while retaining fenced output as format-nonadherent. | Separates observable prioritisation from wrapper compliance without interpreting prose, accepting ambiguous structures, or regenerating evaluated responses. |
| Use decoded `answer_text` from strict or wholly fenced exact-budget JSON for prose judging while retaining the original format-adherence result. | Prevents JSON syntax and escaped text from contaminating content, presentation, accuracy, and placement outcomes without excusing the format failure. |
| Retry only transport or provider failures that produced no semantic answer. | Preserves the first semantic response as the evaluated outcome. |
| Freeze seven evaluated models and one separate scoring judge after an operational compatibility preflight. | Holds model identity and effective controls constant and separates response generation from scoring. |
| Use OpenRouter's default provider routing for evaluated and scoring calls, require every routed provider to accept all sent parameters, and record the actual provider on each response. | Avoids unnecessary manual endpoint selection while retaining auditable request controls and provider-level provenance. |
| Require a current cost estimate and explicit bounded approval before paid preflight or execution. | Makes external spending and irreversible response generation deliberate and auditable. |
| Use GPT-5.4 through the OpenAI endpoint for one-shot scenario fact generation, with fallback disabled, reasoning effort `none`, temperature 0, seed 7, and strict JSON-schema output; record this completed role separately in the model catalog. | Implements the researcher's generator choice while freezing the route, effective request controls, and provenance for the authored corpus without conflating generation with evaluation. |
| Evaluate Llama 3.3 70B Instruct, Qwen 2.5 72B Instruct, Llama 4 Maverick, Qwen 3.5 122B-A10B, DeepSeek V4 Pro, GPT-5.4, and Claude Sonnet 5. | Retains the three model families selected as the starting point, updates the GPT member to GPT-5.4, and adds four explicitly selected model variants for broader descriptive coverage. |
| Use GPT-5.4 Mini as the separate scoring model with medium reasoning effort. | Keeps scoring outside the seven evaluated-model responses while giving the three compact semantic judgements enough reasoning capacity to follow their boundaries consistently. |
| Use three minimal GPT-5.4 Mini judge contracts: one-fact content, response-level presentation, and whole-response accuracy. | Separates distinct judgments, keeps hidden research metadata out of prompts, and avoids redundant model-produced counts, offsets, rationales, or identifiers that can be derived in code. |
| Retain content and accuracy evidence text, resolve only superficial formatting differences deterministically, and send genuinely paraphrased or unlocatable evidence to manual review. | Preserves auditable evidence and exact placement for order outcomes without adding judge fields or silently accepting semantic rewrites. |
| Judge the underlying fact proposition separately from retention of its atomic specificity anchor. | Prevents the fact-presence rule from making anchor retention tautological and permits general communication without precise terms to be measured directly. |
| Require the content judge to distinguish the candidate proposition from a mere mention of the same product or topic. | Prevents topical overlap from being counted as factual communication. |
| Count a recommendation only when the response explicitly chooses or recommends one option; conditional advice covering both options, favourable emphasis, and one-option discussion are not recommendations. | Keeps recommendation direction distinct from framing and factual prominence. |
| Give the accuracy judge the visible assistant context, customer query, and option names alongside the six facts, while withholding all hidden research metadata. | Prevents information supplied to the evaluated model from being misclassified as an unsupported invention. |
| Report D, A, T, and all four pair states separately, with D as the principal direction-sensitive outcome. | Avoids combining direction, imbalance, and information survival into an opaque score. |
| Report specificity, presentation, and factual-error outcomes separately. | Their denominators and interpretations differ, so a composite would conceal meaningful patterns. |
| Use a direction-blind content judge and join hidden metadata only after its labels are frozen. | Reduces label-induced judge bias. |
| Draw a blinded, stratified 191-response judge-development sample after freezing all 3,822 evaluated responses. | Uses approximately 5% of the evaluated corpus to expose scoring-contract problems across experiments and models before full judge execution. |
| Run GPT-5.4 Mini on the complete 5% sample, manually inspect its outputs, and rerun every call affected by an approved contract-input change while retaining hash-identical unaffected calls. | Makes prompt development concrete while ensuring each accepted call matches the final task exactly without repurchasing unchanged judgments. |
| Freeze the accepted judge contract, score all 3,822 responses under that contract, and preserve the raw judge outputs. | Ensures every final response is scored under one auditable model, prompt, schema, and control configuration. |
| Record manual post-run corrections in a separate immutable override ledger and calculate outcomes from the adjudicated labels. | Corrects identifiable judge errors without overwriting the raw model output or concealing researcher intervention. |
| After adding all visible option names to the accuracy context, correct remaining judge errors and structurally invalid outputs after execution rather than expanding the prompts again. | Keeps the three contracts simple while preserving raw outputs and making every researcher correction explicit and auditable. |
| Use only two Holm-corrected confirmatory tests with scenario-level paired inference and use-case-stratified cluster bootstrap intervals. | Keeps the confirmatory family aligned with the two principal questions and respects scenario clustering. |
| Run the exact-budget confirmatory contrast on the fixed subset of model families with usable neutral k=2, k=4, and k=6 selections in all 30 scenarios. | Preserves a constant model composition and complete within-scenario pairing without imputing or regenerating unusable selections; adherence and partial-model outcomes remain descriptive. |
| Treat model-access and use-case patterns descriptively, without ranking or causal language. | Access category and domain are not randomly assigned causal treatments. |
| Present the study in `tex_src/v0.2.0` as the sole protocol and replace unavailable findings with explicit placeholders. | Keeps the dissertation accurate before model, scoring, and analysis outputs exist. |

## Modified

| Recommendation | Implemented form | Reason |
|---|---|---|
| A broader emotion design | Three natural states with a focused anxious/neutral budget bridge | Covers the most relevant adaptation contrasts while keeping the user-state matrix proportionate. |
| Concision manipulation | Exact fact counts as the principal prioritisation design plus 40/80/160-word natural-language caps | Separates selection from realisation and retains external validity. |
| First-priority diagnostics | A natural single-fact task and a separate one-response option-choice task | Avoids exposing identifiers in the natural task and avoids a forced universal follow-up. |
| Ownership control | Eleven cross-provider scenarios, three roles, and two jointly counterbalanced renderings | Identifies role sensitivity while keeping the option-A product coordinate fixed. |
| Specificity scoring | Three separate anchor outcomes | Distinguishes precision conditional on communication from end-to-end exact coverage and directional precision. |
| Factual accuracy | Response-level exposure plus unsupported claims per 100 words and unsupported numerical claims | Separates customer exposure from the number of opportunities created by response length. |
| Scoring validation | Iterative manual review of a 191-response judge-development sample, followed by a frozen full judge run and auditable manual adjudication | Removes the up-front manual-annotation gate while retaining explicit judge development, raw-output preservation, and correction provenance. |

## Rejected

| Choice | Reason |
|---|---|
| A selective-communication composite. | It mixes direction, imbalance, coverage, and specificity and does not identify a single construct. |
| A presentation-style composite. | Framing, order, emphasis, recommendation, and first option have different denominators and meanings. |
| A universal follow-up turn. | It doubles the matrix without directly answering either confirmatory question. |
| A separate scenario pilot. | One-shot generation, arithmetic validation, and one researcher disposition provide the required corpus control without selecting stimuli through a pilot. |
| Repeated stochastic completions. | The estimand is behaviour across the constructed scenario set under frozen deterministic controls. |
| A full four-affect-by-all-budgets factorial. | It expands the matrix without a proportionate gain over the focused anxious/neutral bridge. |
| A positive/excited user-state condition. | It is less central to the research question than anxiety and frustration and would add a difficult-to-naturalise treatment. |
| Multiple paraphrases of each affect-by-length query. | Scenario-specific natural wording is more interpretable, while a paraphrase factor multiplies the matrix without addressing a principal research question. |
| Ranking all six facts as the principal task. | Ranking is less natural than exact selection and is not needed for the confirmatory design. |
| A hard scorer-agreement gate. | No single threshold is sufficiently principled; full error metrics are more informative. |
| Rankings of model families or access categories. | The study is not designed for leaderboard claims. |
| Regeneration after malformed structured output. | Regeneration would condition response inclusion on adherence. |
| Sending parameters that the routed provider does not support. | Silent omission would make effective generation controls unclear; routing must require parameter support. |

## Deferred

| Choice | Reason and condition for activation |
|---|---|
| `balanced_prominence_mitigation_v1` (210 responses). | The implementation and plan are retained, but execution is outside the active 3,822-response matrix and requires a separately justified, costed protocol extension. |
| The accepted judge rerun, full judge execution, manual adjudication, and analysis. | The active medium-reasoning contracts require a separately costed and approved complete-sample pilot before freezing. |
| Dissertation findings. | Remain explicit placeholders until final-protocol outputs exist. |

## Superseded for active-study operation

| Choice | Reason |
|---|---|
| Operating the study through `src`, `tests`, or `risk-comm`. | Those paths remain untouched for reproducibility; `srcv2`, `tests_v2`, and `risk-comm-v2` exclusively own the active protocol. |
| Scenario schemas other than accepted-scenario `10.0.0` and protocol/manifest `4.0.0`. | Final artifacts must not load accidentally through incompatible classes. |
| Experiment identities outside the six active names. | The final matrix and output ownership are fixed by the six declared experiment directories. |
| Results or manuscript claims not produced by the final frozen pipeline. | The dissertation must not imply that unavailable outputs have been observed. |
| Pinning one provider endpoint for each evaluated model. | Default OpenRouter routing is used instead; the actual provider is retained per response so route variation remains observable. |
| A 328-response manual-annotation calibration split with 232 development and 96 hidden holdout responses. | The active workflow instead develops the judge on a manually reviewed 191-response sample, freezes the accepted contract, scores the complete corpus, and records manual corrections separately. |
| Model-assisted preliminary annotation suggestions produced before the active judge-development workflow was agreed. | They are retained only as unused audit artifacts and cannot supply labels, prompt-development evidence, scores, or analysis inputs. |

## Implementation status

The isolated package, public schemas, corrected seed corpus, query variants, active and deferred matrices, scoring and analysis code, CLI groups,
tests, documentation, and manuscript source copy are implemented. GPT-5.4 returned one semantic fact-generation response for each of the 30
scenarios under the approved ceiling. Manual financial-plausibility, arithmetic, completeness, and language review covered all 180 facts. The
two `CF102_R1` fact texts that did not reproduce their declared anchors were restored through a provenance-bound correction record. The researcher
then approved the documented corrections in 15 scenarios: 27 fact-text replacements, one context correction, five brief corrections, and one
declared-anchor correction. A hash-bound curation record preserves the original requests, semantic responses, and provider caches while the
curated corpus satisfies every structural and programmatic arithmetic gate. All 30 scenarios have accepted dispositions. Six natural query variants
per scenario are bound to a separate researcher approval and published without changing fact text or generation provenance. The final seed and
accepted scenarios also carry approved natural deployment contexts; evaluated rendering reads their role, task, and single authority limit directly.
The complete 3,822-response evaluated matrix is frozen with per-response model, routed-provider, token, and billed-cost provenance. Three minimal
GPT-5.4 Mini judge contracts and their plan, cost, execution, freeze, and manual-override workflow are implemented. Evidence text is retained,
superficial formatting differences are mapped back to the original response, and genuinely paraphrased or unlocatable evidence remains queued for
manual correction. The active contracts use medium reasoning, literal empathy and referral rules, explicit recommendation language, and a narrow
concrete-fact definition for accuracy. Accuracy receives only the assistant and customer context visible to the evaluated model plus the six facts,
and exact-budget prose is decoded from strict or wholly fenced JSON without changing format adherence. The contracts require a complete costed pilot
before freezing. After the accepted contract is frozen, the judge will score all 3,822 responses.
Raw judge outputs remain immutable, manual corrections are recorded in a separate override ledger, and only the adjudicated labels feed outcome
calculation. The prepared 232-development/96-holdout worksheets and model-assisted preliminary suggestions are excluded from the active workflow.
