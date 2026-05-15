# Dissertation Distinction Guide
**UCL Institute of Finance & Technology — IFTE0008 MSc Research Project**

> This document translates the official marking rubric and 2025–26 guidelines into active writing instructions.
> Return to this guide before drafting each section, and again during revision.

---

## Programme Context

- **Module**: IFTE0008 (60 credits — one third of overall MSc assessment)
- **Submission deadline**: 1 September 2026 (via Turnitin on Moodle, PDF)
- **Word limit**: 10,000 words maximum (see exclusions below)
- **Referencing style**: Harvard throughout
- **Topic**: Must be finance-related. Your second marker may come from any discipline — write for a technically literate reader who is not a specialist in AI deception detection.

---

## How Marks Are Awarded

Your dissertation is assessed across **four criteria**:

| # | Criterion | Distinction threshold |
|---|-----------|----------------------|
| 1 | Breadth & understanding of background knowledge + independence of thought | 70%+ (A−) |
| 2 | Research design: objectives, methods, appropriateness of reasoning | 70%+ (A−) |
| 3 | Novelty & significance of research outcomes (given problem difficulty) | 70%+ (A−) |
| 4 | Communication: report structure, English expression, data presentation | 70%+ (A−) |

A **distinction = 70% overall (A−)**. An **A+ (90–100%)** means publishable-in-a-peer-reviewed-journal quality.

> **Critical note from the 2025–26 guidelines**: A quantitative component is **strongly encouraged**, particularly for high-grade classifications. Purely qualitative research is strongly discouraged. For a dissertation on AI deception detection, this means your methodology must include empirical experiments, quantitative evaluation metrics, or computational analysis — not just theoretical framing or interviews.

---

## Required Dissertation Structure

The guidelines mandate this exact order. Do not deviate.

| Section | Notes |
|---------|-------|
| 1. Cover Page | Official cover from IFTE0008 Moodle — include as-is |
| 2. Title Page | Title (no acronyms), full name as registered at UCL, institution, year, degree programme |
| 3. Abstract | Self-contained, stand-alone. Summarise problem, method, key result, significance. Do NOT just list objectives. |
| 4. Acknowledgements | Sponsors, data providers, industry partners |
| 5. Table of Contents | |
| 6. List of Figures | |
| 7. List of Tables | |
| 8. Introduction | Background & context, importance of study, how dissertation is structured |
| 9. Literature Review | Critical review of journals, books, online sources; identifies gaps; positions your research |
| 10. Data *(if applicable)* | Data sources, collection/processing method, any manipulations (outlier removal, format transformation) |
| 11. Methodology & Analysis | Methods used — experimental design, software development, statistical techniques |
| 12. Results | Systematic presentation of findings with tables, graphs, diagrams |
| 13. Discussion | How well research addressed original questions; comparison with literature; limitations and improvements |
| 14. Conclusions & Recommendations | Summary of key findings; suggestions for future research |
| 15. References | Harvard style |
| 16. Appendices *(if necessary)* | |

**Core ratio**: Methodology + Results + Discussion should constitute approximately **60% of the dissertation**. Introduction, literature review, and framing sections make up the remaining 40%.

---

## Word Count — What Is and Is Not Counted

| Included in 10,000 words | Excluded from 10,000 words |
|--------------------------|---------------------------|
| All main body text | Title page and signed declaration |
| Introduction through Conclusions | Table of contents, list of figures, list of tables |
| | Abstract |
| | Mathematical formulas and equations |
| | Code |
| | Diagrams, tables, figures, graphs |
| | Footnotes |
| | Reference list |
| | Appendices |

---

## Formatting Requirements

- **Font**: Arial or Helvetica, minimum size 10
- **Line spacing**: 1.5 for main text; single-spaced for indented quotations, tables, footnotes
- **Pagination**: Arabic numerals (1, 2, 3…) consecutively from the title page through appendices
- **Diagrams**: Must be clearly printed; if copied from a source, redraw if necessary and always cite. Diagrams are included within the dissertation (not attached separately).

---

## Criterion 1 — Background Knowledge & Independent Thought

### What the rubric says at distinction level (70–79%)
> *Demonstration of critical thought, extra-curricular reading, and excellent understanding of literature.*

### What you must do

- **Read beyond the obvious.** For AI deception detection, the literature spans AI safety, multi-agent systems, game theory, NLP/LLM interpretability, behavioural economics, and financial fraud detection. Draw from all relevant adjacent fields — not just the most obvious "AI lies" papers.
- **Cite with purpose.** Every citation should directly support, contrast, or contextualise your argument. Remove decorative citations.
- **Show your thinking, not just their thinking.** After summarising what others found, always follow with your own synthesis: *"This suggests..."*, *"A limitation of this approach is..."*, *"Taken together, these studies indicate..."*
- **Harvard referencing, applied consistently.** This means in-text author–date citations and a complete reference list. Apply to every source including figures, datasets, and code libraries.
- **Write a critical literature review, not a summary.** Identify the gaps, contradictions, and unresolved debates your research responds to. The examiner should finish your literature review understanding exactly why your specific research question exists and why it has not already been answered.

### For your specific topic: AI deception detection

Your literature review must cover at minimum:
- What "deception" means in the context of AI agents (strategic misrepresentation vs. hallucination vs. reward hacking — distinguish these clearly)
- Existing detection methods in AI safety and multi-agent settings
- The financial context: why deception in AI agents is a problem for finance specifically (e.g., trading agents, advisory systems, fraud)
- Any empirical benchmarks or datasets already used in this area

Gaps to explicitly identify: What detection methods exist only in theory? What has only been tested in toy environments? What has never been evaluated on financially-relevant behaviour?

### To aim for A/A+ (80–100%)
> *Evidence of extra-curricular academic reading, critical thought and original interpretation* (A)
> *Exceptional insight into the problem and its wider context* (A+)

- Read foundational papers in AI alignment (not just the applied deception papers) to frame your work in a broader intellectual context.
- Include your own interpretive voice: where does the existing consensus seem incomplete or underspecified?
- Connect the literature explicitly to your experimental design — the literature review should make your methodology feel inevitable.

---

## Criterion 2 — Research Design

### What the rubric says at distinction level (70–79%)
> *Some minor faults in execution or understanding with good evidence of original thought.*

### What you must do

- **State your research questions or objectives explicitly and early.** List them numerically in the Introduction. Every chapter that follows should be traceable back to these.
- **Justify every methodological choice.** Do not just describe what you did — explain *why* you chose this method over alternatives. This is the primary signal of independent thought.
- **Align methods to questions.** After drafting your methodology, read each RQ alongside each method. If a method does not directly address a stated objective, either remove the method or add the objective.
- **Quantitative evaluation is required.** For an AI detection system, this means defining measurable performance metrics (precision, recall, F1, AUC, calibration, etc.) and reporting them clearly. Qualitative observations are supporting evidence, not a substitute.
- **Execute correctly.** Check your evaluation setup for data leakage, train/test contamination, and appropriate baselines. One serious methodological flaw will drop you below distinction.
- **Show you understand your method's limitations.** A distinction student discusses where their detection approach could fail or be gamed; a failing student implies it is perfect.

### For your specific topic: AI deception detection

Be precise about what you are detecting and how. The examiner will ask:
- How do you operationalise "deception"? (Strategic misalignment? Misrepresentation under interrogation? Behavioural inconsistency?)
- What is your experimental setup? (Simulated agents? Real LLM outputs? Labelled dataset?)
- What is your baseline? (Random classifier? Human judgement? Prior published method?)
- What are the failure modes of your detector?

Define each of these before you begin writing your methodology section, and ensure the written section answers all of them.

### To aim for A/A+ (80–100%)
> *Only very minor faults in execution or depth of understanding, clearly original thought* (A)
> *Faultless execution, exemplary analysis with entirely appropriate methods, unquestionable originality* (A+)

- Propose a novel combination of methods or an extension to a standard approach that is motivated by the specific properties of AI deception.
- Run ablation studies or robustness checks and report them.
- Anticipate the examiner's methodological questions and pre-empt them in writing.

---

## Criterion 3 — Novelty & Significance of Research Outcomes

### What the rubric says at distinction level (70–79%)
> *Contribution to field (e.g., publishable at domestic conference or poster publication).*

### What you must do

- **Produce a concrete, original output.** A distinction requires something new — a new detection method, a new experimental finding, a new benchmark, a new framework — not just replication of what already exists.
- **Frame your findings as a contribution explicitly.** In your conclusions, state: *"This study contributes X to the field of AI agent deception detection by doing Y, demonstrated through Z."*
- **Do not over-claim or under-claim.** State what your results actually show. A modest but rigorously demonstrated finding is worth more than a grand unsubstantiated one.
- **Connect results back to the literature.** What do your findings confirm, challenge, or add nuance to? This is what the Discussion section is for.
- **Choose a hard enough problem.** A trivially easy task executed perfectly scores lower than a hard task executed well. AI deception detection in a financially-relevant setting is inherently hard — make sure your problem setup reflects that difficulty.

### For your specific topic: AI deception detection

Novelty in this area can come from:
- A new detection mechanism or probe applied to agent behaviour
- A new experimental environment that better reflects real financial AI deployment
- New empirical findings about when/how current AI agents exhibit deceptive behaviours
- A quantitative comparison of existing detection approaches on a common benchmark

Even if your primary contribution is empirical rather than theoretical, it must produce findings that are non-obvious and non-trivial.

### To aim for A/A+ (80–100%)
> *Challenging project leading to significant contribution to field* (A — conference-publishable)
> *Extremely challenging project leading to outstanding contribution* (A+ — journal-publishable)

- Aim for findings you and your supervisor would consider submitting to a venue like NeurIPS, ICML, FinNLP, or an AI safety workshop.
- Clearly situate your contribution within the state of the art — by the end of your paper, the examiner should understand exactly what did not exist before your dissertation.
- Negative or null results are valid if your methodology is rigorous and your analysis of why the detector failed or why deception did not manifest is insightful.

---

## Criterion 4 — Communication: Structure, English, Data Presentation

### What the rubric says at distinction level (70–79%)
> *Good project write up with very clear logical structure and good presentation of data.*

### What you must do

- **Follow the mandated structure** (see table above). Every chapter should open with a statement of its purpose and close with a brief summary linking forward.
- **Write for your second marker.** They may not be an AI specialist. Every technical term — agent, deception, alignment, reward hacking, prompt injection, etc. — must be defined the first time it appears.
- **Present all data in labelled, well-formatted figures and tables.** Every figure needs: a number, a self-contained caption, axis labels with units, and a legend. Never make the reader consult the text to understand a figure.
- **Never paste raw output.** Reformat model outputs, code results, and evaluation logs into clean tables or visualisations.
- **Proofread rigorously.** Grammatical errors, inconsistent terminology, and undefined abbreviations signal a rushed submission. Read aloud, use a grammar checker, and have a peer read a full draft before submission.
- **Harvard referencing throughout** — including in figure captions when reusing images from other sources.

### To aim for A/A+ (80–100%)
> *Excellent write up with only minor faults, highly readable, extremely clear with excellent structure* (A)
> *Excellent write up both in terms of readability, clarity and structure, with faultless presentation of data* (A+)

- Apply information design principles to figures: maximise data-ink ratio, use colour purposefully, keep style consistent across all figures.
- Write an abstract that stands completely alone: problem, method, key quantitative result, significance. No undefined acronyms.
- Your discussion should read as genuine intellectual engagement with your own results — not a restatement of what the results section already said.

---

## Cross-Cutting Rules (Apply Everywhere)

1. **Signpost relentlessly.** Tell the reader what you are about to do, do it, then briefly confirm what you just did. *"Chapter 3 presents the methodology. Section 3.1 justifies the choice of..."*

2. **Every claim needs evidence.** An unsupported assertion is worth nothing. If you cannot cite it or demonstrate it, either remove it or frame it explicitly as your own conjecture.

3. **Be precise about scope.** Never claim findings generalise beyond what your data and method support. If you tested deception detection on one class of LLM in one experimental setting, say so.

4. **Original thought must be visible.** Do not hide your own analysis behind passive voice and constant citation. When you are making your own argument, write in first person if needed.

5. **The whole document must form one argument.** Abstract → Introduction → Literature Review → Methodology → Results → Discussion → Conclusions is one arc. Revise with the whole arc in mind, not section by section in isolation.

6. **Work independently.** Your supervisor will not review full drafts. Draft a table of contents early, share it with your supervisor, then execute. Proactively manage your own timeline.

---

## Pre-Submission Checklist

### Content
- [ ] Research questions/objectives stated numerically in the Introduction
- [ ] Every method justified (not just described) with alternatives considered
- [ ] Literature review is critical, identifies gaps, positions your specific contribution
- [ ] Quantitative evaluation metrics defined and reported
- [ ] Results compared to a meaningful baseline
- [ ] Discussion evaluates how well each RQ was addressed
- [ ] Conclusions explicitly state the contribution to the field
- [ ] Limitations section is honest and specific

### Formatting & Compliance
- [ ] Official cover page from Moodle included as page 1
- [ ] Title page contains all required fields (name as registered, UCL, year, degree programme)
- [ ] Abstract is self-contained and includes a key quantitative result
- [ ] All figures/tables numbered, captioned, and legible
- [ ] Harvard referencing applied consistently throughout, including figures
- [ ] Font Arial/Helvetica, minimum size 10, 1.5 line spacing
- [ ] Pages numbered consecutively in Arabic numerals from title page
- [ ] Word count verified (≤10,000, main body only — code, figures, references excluded)
- [ ] Submitted as PDF via Turnitin on IFTE0008 Moodle page before 1 September 2026
- [ ] No plagiarism — all referenced material summarised in your own words

### Final quality check
- [ ] Proofread aloud for grammar, flow, and consistency
- [ ] Every technical term defined on first use
- [ ] No raw output pasted; all results reformatted
- [ ] Second marker test: would a non-AI-specialist understand your contribution?

---

*Sources: UCL CEGE MSc Project Marking Criteria; UCL IFT Student Guidelines for the Research Project (IFTE0008) 2025–26. Distinction = 70%+. Grade boundaries: A+ 90–100%, A 80–89%, A− 70–79%.*
