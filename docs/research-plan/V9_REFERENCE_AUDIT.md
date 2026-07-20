# V9 primary-source reference audit

Audit date: 19 July 2026. Scope: metadata resolution and whether V9's central prose is bounded by the cited primary source. This is not a claim that future experimental results exist.

| Reference | Primary source | Metadata/prose result |
|---|---|---|
| JANUS | https://arxiv.org/abs/2606.10852 | Resolves as *JANUS: A Benchmark for Goal-Conditioned Information Distortion in LLMs*. V9's description of fixed fact pools and selection/framing/emphasis measures is supported. |
| DECOR | https://arxiv.org/abs/2605.19270 | Resolves as *DECOR: Auditing LLM Deception via Information Manipulation Theory*. V9's atomic information-manipulation framing is supported. |
| Unified taxonomy | https://arxiv.org/abs/2604.04788 | Resolves as the cited hallucination-to-scheming taxonomy/benchmark analysis. V9 uses it only to separate behavioural misleadingness mechanisms from intent claims. |
| Social Sycophancy | https://arxiv.org/abs/2505.13995 | Resolves with the cited title. V9 does not use it to infer clinical anxiety or vulnerability. |
| Lost in the Middle | https://arxiv.org/abs/2307.03172 | Resolves with the cited title and supports position/order sensitivity motivation. |
| Fostering Appropriate Reliance | https://arxiv.org/abs/2502.08554 | Resolves with the cited title, five listed authors, CHI 2025 comment, and related ACM DOI. Its controlled reliance findings motivate future human validation only; V9 does not infer human reliance from the automated benchmark. |
| To Rely or Not to Rely? | https://arxiv.org/abs/2412.15584 | Resolves with the cited title, three listed authors, and CHI 2025 journal reference. Its randomized human reliance study is used as future-study context, not as evidence that V9 measures reliance. |
| FCA consumer understanding | https://www.fca.org.uk/publications/good-and-poor-practice/consumer-understanding-good-practice-areas-improvement | Primary FCA page supports the bounded motivation around testing customer understanding; V9 explicitly is not a compliance test. |
| Lost in Simulation | https://arxiv.org/abs/2601.17087 | Resolves with the cited title. Retained as background only; V9 removes the simulator implementation entirely. |
| Simulated Customers Never Walk Away | https://arxiv.org/abs/2606.20708 | Resolves with the cited title and sole listed author. Retained only to explain why simulated-user decision fidelity and user-harm measurement are excluded from the active protocol. |
| Reliability without Validity | https://arxiv.org/abs/2606.19544 | Resolves with the cited title and supports empirical validation rather than treating judge agreement as validity. |
| Agreement Metrics for LLM-as-Judge | https://arxiv.org/abs/2606.00093 | Resolves with the cited title and supports reporting multiple agreement/error measures. |
| Deceptive Explanations (CHI 2025) | https://doi.org/10.1145/3706598.3713408 | DOI, title, and the four-author record (Danry, Pataranutaporn, Groh, and Epstein) resolve. The audit corrected the supplied plan's erroneous extra author and author order. V9 does not generalise this human belief-change result to the benchmark without a human study. |
| Behavioural Indicators of Overreliance (CHI 2026) | https://doi.org/10.1145/3772318.3790332 | DOI resolves; used only as future human-reliance context after user-harm measurement was deferred. |
| Belief Updating and Delegation (CHI 2026) | https://doi.org/10.1145/3772318.3790775 | DOI resolves; used only as future human-study context. |
| FCA vulnerable-circumstances review | https://www.fca.org.uk/publications/good-and-poor-practice/delivering-vulnerable-customers | Primary FCA page resolves with the cited title and March 2025 publication context. V9 uses it only as domain motivation and does not claim regulatory compliance. |
| FCA challenging-times blog | https://www.fca.org.uk/news/blogs/support-customers-challenging-times | Primary FCA page resolves with the cited title and 14 May 2026 date. Its examples support the domain relevance of clear, prominent information and signposting, without defining V9's empirical outcomes. |
| FCA vulnerable-customer guidance | https://www.fca.org.uk/publications/finalised-guidance/guidance-firms-fair-treatment-vulnerable-customers | Primary FCA page resolves as the February 2021 guidance, last updated March 2025. V9 does not classify the worried cue as vulnerability and does not present the benchmark as a legal or compliance assessment. |

All 18 numbered V9 references resolve to their cited primary records, and the active V9 claims remain narrower than their source claims. Before dissertation
submission, citation metadata must also be reconciled with `tex_src/references.bib` and every prose citation rechecked after the literature review is rewritten.
