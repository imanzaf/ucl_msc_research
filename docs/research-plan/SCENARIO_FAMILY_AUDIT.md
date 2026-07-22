# Scenario-family audit for the V0.5.1 seed

**Audit date:** 22 July 2026  
**Scope:** `data/inputs/scenarios/v0.5.1/scenario_generation_seeds.json`

## Measurement boundary

The scenarios are controlled environments for measuring financial risk communication, not model financial competence, recommendation quality, user behaviour, or realised harm. The primary outcome is whether a model gives less disclosure credit to an adverse fact than to its matched favourable fact when both are equally required. The experiment then tests whether that gap changes under a tight word budget or a minimal worried cue. A generic follow-up measures whether initially omitted material facts are repaired.

Each family should therefore provide:

- a plausible customer-facing explanation or comparison task;
- exactly two adverse and two favourable facts that are all required for a complete answer;
- material facts that can be matched on specificity, complexity, and source prominence;
- a decision context in which omission can distort understanding without asking the model to make the decision; and
- enough information density for the calibrated 80–115-word tight condition to create pressure without making complete disclosure impossible.

The inactive `potential_harm_pathway` fields document why a fact could matter, but they are not supplied to evaluated models and are not part of an active harm measure.

## Current deployment evidence

The deployment landscape does not supply ten equally common customer-facing tasks. It supports a smaller number of broad deployment classes, which this benchmark instantiates across different retail-finance journeys:

- The 2026 Cambridge Centre for Alternative Finance survey reports that AI-powered customer support is the most widely adopted front-office use case (73%). Fraud detection (57%) and credit risk and underwriting (54%) are the leading risk-and-compliance uses. It also reports adoption in payment monitoring, investment research, portfolio intelligence, professional advice, insurance risk and underwriting, and claims management, although the specialised uses are less prevalent. Source: [The 2026 Global AI in Financial Services Report](https://www.jbs.cam.ac.uk/wp-content/uploads/2026/05/ccaf-2026-04-28-global-ai-in-financial-services-report-2.pdf), pp. 31–34.
- The FCA's July 2026 Mills Review likewise identifies customer support as the most common front-office use and fraud detection and credit-risk modelling as prominent risk uses. It distinguishes routine explanatory servicing from higher-risk disputed-transaction and fraud investigations, which are more likely to retain human review. Source: [The Mills Review: AI and the future of retail financial services](https://www.fca.org.uk/publication/corporate/the-mills-review.pdf), pp. 13 and 26–28.
- The EBA reports that 55% of surveyed banks already use general-purpose or agentic AI in consumer-facing processes. The most common uses include detecting and notifying customers of suspicious activity, assisting service staff, and automating information or guidance for customer self-service. Source: [Rising application of AI in EU banking and payments](https://www.eba.europa.eu/sites/default/files/2025-09/146b3558-d026-47bf-a872-f05e93ed30d2/Rising%2520application%2520of%2520AI%2520in%2520EU%2520banking%2520and%2520payments%2520sector.pdf), p. 2.
- The 2024 Bank of England/FCA survey found retail banking and general insurance to be the second- and third-largest business areas by reported use-case share, after operations and IT. It also found strong expected growth in customer support and fraud detection. Source: [Artificial intelligence in UK financial services – 2024](https://www.bankofengland.co.uk/report/2024/artificial-intelligence-in-uk-financial-services-2024).
- For retail investments, ESMA explicitly identifies customer support and assistance with investment advice and portfolio management as AI uses that engage investor-protection obligations. Source: [ESMA statement on AI and investment services](https://www.esma.europa.eu/press-news/esma-news/esma-provides-guidance-firms-using-artificial-intelligence-investment-services).

This evidence supports a benchmark centred on bounded customer support and explanation, with journeys that expose credit, fraud, payment, investment, pension, insurance, and financial-difficulty risks. It does not justify treating the ten families as a prevalence-weighted sample of all financial AI. Back-office process automation, cybersecurity, AML/KYC, and internal risk modelling are intentionally excluded because they do not directly present a customer-facing risk-communication turn.

## Family decisions

| ID | Decision | Assessment and action |
|---|---|---|
| CF001 | Retain | Cash-flow explanation is a plausible personalised-servicing task and produces two clear benefit/risk pairs. The user request was rewritten as a concrete question about a new monthly payment. |
| CF002 | Retain | Savings comparison creates a strong return-versus-access trade-off without requiring advice. The request now identifies emergency savings naturally instead of asking for generic “main points.” |
| CF003 | Retain | Balance-transfer servicing is narrower than generic credit underwriting but supplies unusually clean matched facts: promotional benefit versus fee, and repayment progress versus reversion risk. It remains distinct from instalment-loan consolidation. |
| CF004 | Retain | Debt consolidation directly tests whether a lower monthly payment crowds out total-cost and term information. The request was rewritten in the customer's own management goal. |
| CF005 | Retain | Mortgage comparison has material near-term and later-payment risks, strong numerical matching, and high consumer consequence while remaining an explanation rather than a suitability decision. |
| CF006 | Retain | Financial-difficulty support is a high-relevance servicing deployment in which reassuring short-term relief can crowd out longer-term cost or credit-file consequences. Human signposting remains inside the authority boundary. |
| CF007 | Retain | Portfolio explanation is supported by current investment-service deployment evidence and provides clear performance-versus-downside and feature-versus-cost pairs. The request no longer presupposes that a change should be made. |
| CF008 | Refine | The old family mixed contribution, drawdown, lump-sum, and transfer journeys, weakening replication comparability and use-case-level budget calibration. It is now a coherent pension-drawdown family covering starting, increasing, and structuring withdrawals. |
| CF009 | Retain | Insurance comparison represents customer support around pricing and coverage outputs. Premium/excess and coverage/exclusion pairs make risk communication observable without asking the model to underwrite or determine a claim. |
| CF010 | Replace | A later disputed-payment case update was less representative of the common consumer-facing fraud workflow and sat close to a human-reviewed investigation. It is replaced by a suspicious-payment alert explainer that communicates transaction status, continuing exposure, active protections, restrictions, and response deadlines without deciding whether fraud occurred. |

## Prompt-language decision

All ten `core_initial_request` values were rewritten. The previous requests repeated the benchmark phrase “explain the main points I should understand,” which made unrelated customers sound identical and explicitly solicited comprehensive coverage. The new requests:

- name the customer's concrete situation or goal;
- use ordinary first-person phrasing and contractions sparingly so the prefixed cue still reads naturally;
- avoid enumerating the four scored facts or explicitly asking for all risks and benefits; and
- preserve the same request content in neutral and worried conditions, because emotional wording remains code-owned.

Naturalness and semantic equivalence of the complete cue-plus-request strings must still be checked during the existing prompt-review gate before calibration.
