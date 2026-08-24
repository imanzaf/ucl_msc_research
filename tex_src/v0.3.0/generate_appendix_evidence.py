"""Generate annotated appendix scenarios and frozen response examples."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any, Dict, Iterable, List

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIRECTORY = Path(__file__).resolve().parent
ASSET_DIRECTORY = OUTPUT_DIRECTORY / "assets"
SCENARIO_PATH = REPOSITORY_ROOT / "data" / "inputs" / "scenarios" / "v4.0.1" / "accepted_scenarios.jsonl"
SEED_PATH = REPOSITORY_ROOT / "data" / "inputs" / "scenarios" / "v4.0.1" / "final_scenario_generation_seeds.json"
EXPERIMENT_ROOT = REPOSITORY_ROOT / "data" / "outputs" / "experiments"

APPENDIX_SCENARIO_EXAMPLE_IDS = ("CF103_R1", "CF105_R1")
SEED_EXAMPLE_ID = "CF101_R1"

MODEL_LABELS = {
    "anthropic/claude-sonnet-5": "Claude Sonnet 5",
    "deepseek/deepseek-v4-pro": "DeepSeek V4 Pro",
    "meta-llama/llama-3.3-70b-instruct": "Llama 3.3 70B Instruct",
    "meta-llama/llama-4-maverick": "Llama 4 Maverick",
    "openai/gpt-5.4": "GPT-5.4",
    "qwen/qwen-2.5-72b-instruct": "Qwen 2.5 72B Instruct",
    "qwen/qwen3.5-122b-a10b": "Qwen3.5 122B-A10B",
}

EXAMPLE_RUNS = {
    "user_state_adaptation_v2": (
        "run_93f85601436f1d0cc6b9ce76",
        "run_a071a8c7abcf4b62e4ab6aa4",
    ),
    "information_budget_v1": (
        "run_58ba26b765385f069f122a80",
        "run_d09e1498a8bb5685626e1c06",
    ),
    "word_budget_external_validity_v1": (
        "run_c0ff5ea78ca10de918fb27db",
        "run_a3093e8b9de9a66f0fc6d10e",
    ),
    "single_fact_priority_v1": (
        "run_0bfbaad30f3237c5526aa1a9",
        "run_1c6a80030a4b61b4c87b701a",
    ),
    "ownership_role_control_v1": (
        "run_4799cbcf89639fcd69d48dd3",
        "run_5718ce0cdbc36c44234c8d83",
    ),
    "option_first_v1": (
        "run_c4ae1dce4a5ea58f8742fddd",
        "run_081c4b5f7575f9c45cc7e826",
    ),
    "commercial_interest_instruction_v1": (
        "run_e9d232f237f4e17edb9f6990",
        "run_7d53adf7b36be904373acf44",
    ),
}

NAVY = "#001A57"
CYAN = "#00A6D6"
PURPLE = "#7B1FA2"
MID_GREY = "#5F6B7A"
LIGHT_GREY = "#D7DCE2"
PALE_BLUE = "#E9F7FC"
PALE_PURPLE = "#F3ECF8"
PALE_GREY = "#F5F7F9"


def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    """Yield decoded records from a JSON Lines file."""
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def load_scenarios() -> Dict[str, Dict[str, Any]]:
    """Load the frozen accepted scenarios by identifier."""
    return {record["scenario_id"]: record for record in read_jsonl(SCENARIO_PATH)}


def load_seed(scenario_id: str) -> Dict[str, Any]:
    """Load one frozen generation seed replication by scenario identifier."""
    package = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for use_case in package["use_cases"]:
        for replication in use_case["replications"]:
            if replication["scenario_id"] == scenario_id:
                return {"deployment_context": use_case["deployment_context"], **replication}
    raise KeyError(f"Seed not found: {scenario_id}")


def load_experiment_records(experiment: str) -> Dict[str, Dict[str, Any]]:
    """Join frozen results and final response scores for one experiment."""
    directory = EXPERIMENT_ROOT / experiment
    results: Dict[str, Dict[str, Any]] = {}
    for result_path in sorted((directory / "results").glob("*_results.jsonl")):
        for result in read_jsonl(result_path):
            results[result["run_unit_id"]] = result

    joined: Dict[str, Dict[str, Any]] = {}
    for score in read_jsonl(directory / "scoring" / "response_scores.jsonl"):
        run_id = score["run_unit_id"]
        result = results.get(run_id)
        if result is not None:
            joined[run_id] = {"score": score, "result": result}
    return joined


def validate_scenario(scenario: Dict[str, Any]) -> None:
    """Validate the balanced six-fact structure required by the figure."""
    facts = scenario["facts"]
    if len(facts) != 6:
        raise ValueError(f"{scenario['scenario_id']} does not contain six facts")
    pair_ids = {fact["pair_id"] for fact in facts}
    if len(pair_ids) != 3:
        raise ValueError(f"{scenario['scenario_id']} does not contain three pairs")
    directions = [fact["direction"] for fact in facts]
    if directions.count("owner_supporting") != 3 or directions.count("countervailing") != 3:
        raise ValueError(f"{scenario['scenario_id']} is not directionally balanced")


def wrap(value: str, width: int) -> str:
    """Wrap figure text without breaking words or hyphenating content."""
    return "\n".join(textwrap.wrap(value, width=width, break_long_words=False, break_on_hyphens=False))


def add_box(
    axis: Any,
    x: float,
    y: float,
    width: float,
    height: float,
    facecolor: str,
    edgecolor: str,
    linewidth: float = 1.2,
    radius: float = 0.012,
    padding: float = 0.008,
) -> FancyBboxPatch:
    """Add one rounded rectangle to a scenario figure."""
    box = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad={padding},rounding_size={radius}",
        linewidth=linewidth,
        edgecolor=edgecolor,
        facecolor=facecolor,
    )
    axis.add_patch(box)
    return box


def short_fact_id(fact_id: str) -> str:
    """Return the final fact component used in reader-facing labels."""
    return fact_id.rsplit("_", maxsplit=1)[-1]


def draw_fact_box(axis: Any, fact: Dict[str, Any], x: float, y: float, width: float, height: float) -> None:
    """Draw one annotated fact with direction and specificity anchor."""
    is_supporting = fact["direction"] == "owner_supporting"
    edge = CYAN if is_supporting else PURPLE
    face = PALE_BLUE if is_supporting else PALE_PURPLE
    direction = "Institution-supporting" if is_supporting else "Countervailing"
    fact_text = wrap(fact["text"], 46)
    if len(fact_text.splitlines()) > 3:
        raise ValueError(f"Fact text does not fit its protected body area: {fact['fact_id']}")

    add_box(axis, x, y, width, height, face, edge, linewidth=1.4)
    axis.plot(
        [x + 0.014, x + width - 0.014],
        [y + 0.047, y + 0.047],
        color=edge,
        linewidth=0.6,
        alpha=0.25,
    )
    axis.text(
        x + 0.014,
        y + height - 0.030,
        f"{short_fact_id(fact['fact_id'])}  |  {direction}",
        ha="left",
        va="top",
        fontsize=9.4,
        fontweight="bold",
        color=edge,
    )
    axis.text(
        x + 0.014,
        y + height - 0.071,
        fact_text,
        ha="left",
        va="top",
        fontsize=8.6,
        color=NAVY,
        linespacing=1.12,
    )
    axis.text(
        x + 0.014,
        y + 0.020,
        f"Anchor: {fact['anchor']}",
        ha="left",
        va="bottom",
        fontsize=8.3,
        color=MID_GREY,
        fontweight="bold",
    )


def render_scenario_figure(scenario: Dict[str, Any], destination: Path) -> None:
    """Render one annotated two-option, three-pair scenario figure."""
    validate_scenario(scenario)
    figure, axis = plt.subplots(figsize=(8.6, 7.2))
    figure.patch.set_facecolor("white")
    figure.subplots_adjust(left=0, right=1, top=1, bottom=0)
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")

    add_box(axis, 0.06, 0.875, 0.88, 0.09, PALE_GREY, LIGHT_GREY, linewidth=0.9)
    axis.text(0.08, 0.942, "Decision context", fontsize=9.2, fontweight="bold", color=MID_GREY, va="top")
    axis.text(0.255, 0.942, wrap(scenario["decision_context"], 78), fontsize=9.4, color=NAVY, va="top")

    options = {option["option_id"]: option for option in scenario["options"]}
    option_width = 0.35
    for option_id, x in (("OPTION_A", 0.09), ("OPTION_B", 0.56)):
        option = options[option_id]
        is_associated = option_id == scenario["owner_supporting_option"]
        add_box(axis, x, 0.745, option_width, 0.10, PALE_GREY, LIGHT_GREY, linewidth=1.0)
        axis.text(x + 0.016, 0.823, option_id.replace("_", " ").title(), fontsize=8.3, color=MID_GREY, va="top")
        axis.text(x + 0.016, 0.793, wrap(option["product_name"], 30), fontsize=10.2, fontweight="bold", color=NAVY, va="top")
        if is_associated:
            axis.text(
                x + option_width - 0.016,
                0.823,
                "Institution-associated option",
                fontsize=8.0,
                color=CYAN,
                fontweight="bold",
                ha="right",
                va="top",
            )

    pair_ids = sorted({fact["pair_id"] for fact in scenario["facts"]})
    row_y = (0.52, 0.30, 0.08)
    for pair_number, (pair_id, y) in enumerate(zip(pair_ids, row_y), start=1):
        pair_facts = [fact for fact in scenario["facts"] if fact["pair_id"] == pair_id]
        by_option = {fact["option_id"]: fact for fact in pair_facts}
        valence = pair_facts[0]["customer_valence"].replace("customer_", "").title()
        if len({fact["customer_valence"] for fact in pair_facts}) != 1:
            raise ValueError(f"Pair {pair_id} does not share customer valence")

        axis.plot([0.44, 0.56], [y + 0.09, y + 0.09], color=LIGHT_GREY, linewidth=1.1, zorder=0)
        add_box(axis, 0.458, y + 0.045, 0.084, 0.09, "white", LIGHT_GREY, linewidth=0.9, radius=0.02)
        axis.text(0.5, y + 0.108, f"Pair {pair_number}", ha="center", va="center", fontsize=8.4, fontweight="bold", color=NAVY)
        axis.text(0.5, y + 0.075, valence, ha="center", va="center", fontsize=7.5, color=MID_GREY)

        draw_fact_box(axis, by_option["OPTION_A"], 0.09, y, option_width, 0.18)
        draw_fact_box(axis, by_option["OPTION_B"], 0.56, y, option_width, 0.18)

    mechanism = scenario["facts"][0]["institutional_benefit"]
    add_box(axis, 0.06, 0.004, 0.88, 0.047, PALE_GREY, LIGHT_GREY, linewidth=0.8, padding=0.004)
    axis.text(0.08, 0.040, "Institutional-benefit mechanism", fontsize=8.1, fontweight="bold", color=MID_GREY, va="top")
    axis.text(0.36, 0.040, wrap(mechanism, 72), fontsize=8.4, color=NAVY, va="top")

    figure.savefig(destination, format="pdf", facecolor="white", pad_inches=0)
    plt.close(figure)


def latex_escape(value: str) -> str:
    """Escape frozen prose for ordinary LaTeX text while normalising display punctuation."""
    value = value.replace("**", "")
    value = value.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        "£": r"\pounds{}",
    }
    return "".join(replacements.get(character, character) for character in value)


def response_to_latex(value: str) -> str:
    """Convert a frozen Markdown response into readable LaTeX without changing wording."""
    blocks: List[str] = []
    paragraph: List[str] = []

    def flush_paragraph() -> None:
        """Append the current response paragraph to the output blocks."""
        if paragraph:
            blocks.append(latex_escape(" ".join(paragraph)))
            paragraph.clear()

    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            continue
        if line.startswith("- "):
            flush_paragraph()
            blocks.append(r"\noindent\textbullet\ " + latex_escape(line[2:]))
            continue
        paragraph.append(line)
    flush_paragraph()
    return "\n\n\\par\n".join(blocks)


def format_score(value: float) -> str:
    """Format a discrete response score as an exact reader-facing value."""
    rounded = round(value, 8)
    mapping = {
        -1.0: "-1",
        -2 / 3: r"-\frac{2}{3}",
        -1 / 3: r"-\frac{1}{3}",
        0.0: "0",
        1 / 6: r"\frac{1}{6}",
        1 / 3: r"\frac{1}{3}",
        0.5: r"\frac{1}{2}",
        2 / 3: r"\frac{2}{3}",
        5 / 6: r"\frac{5}{6}",
        1.0: "1",
    }
    for key, display in mapping.items():
        if abs(rounded - key) < 1e-7:
            return display
    return f"{value:.3f}"


def score_triplet(record: Dict[str, Any]) -> str:
    """Return a compact D, A and T score annotation for one response."""
    prose = record["score"]["prose_selection"]
    return (
        rf"\(D={format_score(prose['signed_directional_gap'])}\), "
        rf"\(A={format_score(prose['pairwise_absolute_imbalance'])}\), "
        rf"\(T={format_score(prose['total_material_coverage'])}\)"
    )


def selected_ids(record: Dict[str, Any]) -> str:
    """Return shortened selected fact identifiers for an exact-budget response."""
    identifiers = record["result"]["response"].get("selected_fact_ids") or []
    return ", ".join(short_fact_id(identifier) for identifier in identifiers)


def response_box(title: str, record: Dict[str, Any], annotation: str) -> str:
    """Render one frozen output in a breakable appendix box."""
    run_id = record["score"]["run_unit_id"]
    response = record["result"]["response"]
    answer_text = response.get("answer_text")
    if not answer_text:
        raise ValueError(f"Selected response has no parsed answer text: {run_id}")
    if record["score"]["accuracy"]["response_has_material_error"]:
        raise ValueError(f"Selected response has a material-error flag: {run_id}")
    return "\n".join(
        [
            rf"\begin{{instrumentbox}}{{{latex_escape(title)}}}",
            r"\small",
            rf"\textit{{Final scores: {annotation}. Run: \code{{{latex_escape(run_id)}}}.}}",
            r"\par\smallskip",
            response_to_latex(answer_text),
            r"\end{instrumentbox}",
        ]
    )


def scenario_summary(scenario: Dict[str, Any]) -> str:
    """Return a concise appendix summary of one scenario's decision."""
    first, second = scenario["options"]
    return f"{scenario['decision_context']} The compared options were {first['product_name']} and " f"{second['product_name']}."


def seed_example_tex(seed: Dict[str, Any]) -> str:
    """Create a structured reader-facing representation of one frozen seed."""
    deployment = seed["deployment_context"]
    option_a, option_b = seed["options"]
    lines = [
        r"\section[Generation-seed example: CF101\_R1]{\rev{Generation-seed example: }\revcode{CF101\_R1}}",
        "",
        r"\begin{revisionblock}",
        (
            r"The seed fixed the decision, institutional-benefit mechanism and required fact-pair structure before fact generation. "
            r"Each seed specified six intended propositions and their required anchors; "
            r"the generation model rendered these as concise customer-facing facts. "
            r"The substantive fields from the frozen \code{CF101\_R1} seed are shown below; JSON field order and schema metadata are omitted."
        ),
        r"\end{revisionblock}",
        "",
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Design fields fixed by the generation seed for \code{CF101\_R1}.}",
        r"\label{tab:appendix_seed_cf101_design}",
        r"\small",
        r"\begin{tabularx}{\textwidth}{@{}L{0.23\textwidth}Y@{}}",
        r"\toprule",
        r"\textbf{Seed field} & \textbf{Frozen content} \\",
        r"\midrule",
        rf"Role and task & {latex_escape(deployment['role'])} at {latex_escape(deployment['entity_name'])}; {latex_escape(deployment['task'])} \\",
        rf"Decision context & {latex_escape(seed['decision_context'])} \\",
        rf"Option A & {latex_escape(option_a['company_name'])}: {latex_escape(option_a['option_name'])} \\",
        rf"Option B & {latex_escape(option_b['company_name'])}: {latex_escape(option_b['option_name'])} \\",
        rf"Institutional-benefit mechanism & {latex_escape(seed['owner_benefit_mechanism'])} \\",
        rf"Authority limit & {latex_escape(deployment['authority_limits'][0])} \\",
        r"\bottomrule",
        r"\end{tabularx}",
        r"\end{table}",
    ]
    return "\n".join(lines)


def scenario_table_tex(scenario: Dict[str, Any]) -> List[str]:
    """Create one compact appendix table for an accepted scenario instance."""
    scenario_id = scenario["scenario_id"]
    suffix = scenario_id.lower().replace("_", "")
    options = {option["option_id"]: option for option in scenario["options"]}
    lines = [
        r"\begin{table}[H]",
        r"\centering",
        rf"\caption{{Annotated scenario structure for \code{{{latex_escape(scenario_id)}}}.}}",
        rf"\label{{tab:appendix_scenario_{suffix[:5]}}}",
        r"\footnotesize",
        r"\begin{minipage}{\textwidth}",
        rf"\textbf{{Decision context.}} {latex_escape(scenario['decision_context'])}\par",
        r"\smallskip",
        (
            rf"\textbf{{Options.}} A: {latex_escape(options['OPTION_A']['product_name'])}; "
            rf"B: {latex_escape(options['OPTION_B']['product_name'])}."
        ),
        r"\end{minipage}",
        r"\medskip",
        r"\begin{tabularx}{\textwidth}{@{}L{0.065\textwidth}L{0.13\textwidth}L{0.09\textwidth}L{0.18\textwidth}Y@{}}",
        r"\toprule",
        r"\textbf{Fact} & \textbf{Pair and valence} & \textbf{Option} & \textbf{Direction} & \textbf{Visible proposition and anchor} \\",
        r"\midrule",
    ]
    facts = sorted(scenario["facts"], key=lambda fact: int(short_fact_id(fact["fact_id"])[1:]))
    for fact in facts:
        direction = "Institution-supporting" if fact["direction"] == "owner_supporting" else "Countervailing"
        pair_number = fact["pair_id"].rsplit("P", maxsplit=1)[-1]
        valence = fact["customer_valence"].replace("customer_", "").title()
        option_label = fact["option_id"].replace("OPTION_", "")
        proposition = f"{fact['text']} Anchor: {fact['anchor']}."
        lines.extend(
            [
                (
                    rf"\code{{{latex_escape(short_fact_id(fact['fact_id']))}}} & Pair {latex_escape(pair_number)}; {latex_escape(valence)} & "
                    rf"{latex_escape(option_label)} & {latex_escape(direction)} & {latex_escape(proposition)} \\"
                ),
                r"\addlinespace[0.3em]",
            ]
        )
    mechanism = scenario["facts"][0]["institutional_benefit"]
    lines.extend(
        [
            r"\midrule",
            rf"\multicolumn{{5}}{{@{{}}p{{\textwidth}}@{{}}}}{{\textbf{{Institutional-benefit mechanism.}} {latex_escape(mechanism)}}} \\",
            r"\bottomrule",
            r"\end{tabularx}",
            r"\end{table}",
            "",
        ]
    )
    return lines


def scenario_examples_tex(scenarios: Dict[str, Dict[str, Any]]) -> str:
    """Create compact appendix tables for two additional scenarios."""
    lines = [
        r"\section{Illustrative scenario structures}",
        "",
        r"\begin{revisionblock}",
        (
            "Tables~\\ref{tab:appendix_scenario_cf103} and \\ref{tab:appendix_scenario_cf105} show two further complete scenario instances from "
            "different domains. "
            "Each table identifies option membership, matched customer valence, institutional direction and the registered anchor."
        ),
        r"\end{revisionblock}",
        "",
    ]
    for scenario_id in APPENDIX_SCENARIO_EXAMPLE_IDS:
        lines.extend(scenario_table_tex(scenarios[scenario_id]))
    return "\n".join(lines)


def get_records() -> Dict[str, List[Dict[str, Any]]]:
    """Load and validate the fixed response coordinates selected for the appendix."""
    selected: Dict[str, List[Dict[str, Any]]] = {}
    for experiment, run_ids in EXAMPLE_RUNS.items():
        available = load_experiment_records(experiment)
        records = []
        for run_id in run_ids:
            if run_id not in available:
                raise KeyError(f"Missing selected run {run_id} in {experiment}")
            record = available[run_id]
            if record["score"]["accuracy"]["response_has_material_error"]:
                raise ValueError(f"Selected example has a material error: {run_id}")
            records.append(record)
        selected[experiment] = records
    return selected


def response_examples_tex(records: Dict[str, List[Dict[str, Any]]], scenarios: Dict[str, Dict[str, Any]]) -> str:
    """Create the appendix gallery of scored frozen outputs."""
    lines = [
        r"\section{Frozen response examples across experiments}",
        r"\label{app:response_examples}",
        "",
        r"\begin{revisionblock}",
        (
            "The examples below were selected for interpretive clarity rather than sampled to estimate prevalence. "
            "Response wording is reproduced from the frozen outputs; Markdown emphasis and typographic dashes are normalised for typesetting. "
            "Scores are the final adjudicated response-level values. Single-priority and forced-choice examples compare different models and "
            "therefore "
            "illustrate heterogeneity rather than a treatment effect."
        ),
        r"\end{revisionblock}",
        "",
    ]

    neutral, anxious = records["user_state_adaptation_v2"]
    scenario = scenarios[neutral["score"]["scenario_id"]]
    lines.extend(
        [
            r"\subsection{Customer-state cues: conversational adaptation without selection change}",
            latex_escape(scenario_summary(scenario)),
            "",
            (
                "The scenario, model and short-query length are fixed. Both outputs communicate all six facts with balanced direction and no "
                "pairwise "
                "imbalance; only the anxious response contains the scored reassurance behaviour."
            ),
            "",
            response_box(
                f"Neutral cue | {MODEL_LABELS[neutral['score']['model_slug']]}",
                neutral,
                f"{score_triplet(neutral)}; reassurance: no; {neutral['score']['secondary']['response_word_count']} words",
            ),
            "",
            response_box(
                f"Anxious cue | {MODEL_LABELS[anxious['score']['model_slug']]}",
                anxious,
                f"{score_triplet(anxious)}; reassurance: yes; {anxious['score']['secondary']['response_word_count']} words",
            ),
            "",
        ]
    )

    k2, k6 = records["information_budget_v1"]
    scenario = scenarios[k2["score"]["scenario_id"]]
    lines.extend(
        [
            r"\subsection{Exact information budget: directional selection versus the complete endpoint}",
            latex_escape(scenario_summary(scenario)),
            "",
            (
                r"The same GPT-5.4 coordinate is shown at exact \(k=2\) and \(k=6\). At \(k=2\), the response includes the express option's "
                r"speed and the standard option's delay, two facts that both support the institution-associated express route. At \(k=6\), "
                "all three matched pairs are complete."
            ),
            "",
            response_box(
                "Exact k=2 | GPT-5.4",
                k2,
                f"selected {selected_ids(k2)}; {score_triplet(k2)}",
            ),
            "",
            response_box(
                "Exact k=6 | GPT-5.4",
                k6,
                f"selected {selected_ids(k6)}; {score_triplet(k6)}",
            ),
            "",
        ]
    )

    short, long = records["word_budget_external_validity_v1"]
    scenario = scenarios[short["score"]["scenario_id"]]
    lines.extend(
        [
            r"\subsection{Natural word budget: offsetting one-sidedness}",
            latex_escape(scenario_summary(scenario)),
            "",
            (
                r"The 40-word response omits opposite members from two different pairs. Those omissions cancel in net direction, so \(D=0\), "
                r"while \(A=2/3\) records that the comparison is still one-sided. The 160-word response communicates all six facts."
            ),
            "",
            response_box(
                f"40-word budget | {MODEL_LABELS[short['score']['model_slug']]}",
                short,
                f"{score_triplet(short)}; {short['score']['secondary']['response_word_count']} realised words",
            ),
            "",
            response_box(
                f"160-word budget | {MODEL_LABELS[long['score']['model_slug']]}",
                long,
                f"{score_triplet(long)}; {long['score']['secondary']['response_word_count']} realised words",
            ),
            "",
        ]
    )

    supporting, countervailing = records["single_fact_priority_v1"]
    scenario = scenarios[supporting["score"]["scenario_id"]]
    lines.extend(
        [
            r"\subsection{Single-priority task: contrasting priorities}",
            latex_escape(scenario_summary(scenario)),
            "",
            (
                "These two models receive the same neutral task. Llama prioritises the guaranteed recipient amount supplied by the "
                "institution-associated option; DeepSeek prioritises the rival provider's lower total price. The contrast illustrates why a request "
                "for one priority creates "
                "one-sidedness but does not determine its direction."
            ),
            "",
            response_box(
                f"Institution-supporting priority | {MODEL_LABELS[supporting['score']['model_slug']]}",
                supporting,
                f"{score_triplet(supporting)}; first fact: institution-supporting",
            ),
            "",
            response_box(
                f"Countervailing priority | {MODEL_LABELS[countervailing['score']['model_slug']]}",
                countervailing,
                f"{score_triplet(countervailing)}; first fact: countervailing",
            ),
            "",
        ]
    )

    employer_a, employer_b = records["ownership_role_control_v1"]
    scenario = scenarios[employer_a["score"]["scenario_id"]]
    lines.extend(
        [
            r"\subsection{Institutional affiliation: order changes while facts remain complete}",
            latex_escape(scenario_summary(scenario)),
            "",
            (
                "The scenario, model and rendering are fixed while the fictional employer changes. The employer-associated option is introduced "
                "first in "
                "both outputs, but all six facts remain present and directionally balanced. This is an ordering example, not selective omission."
            ),
            "",
            response_box(
                "Employer associated with Norchester | Llama 3.3 70B Instruct",
                employer_a,
                f"{score_triplet(employer_a)}; employer-associated option first",
            ),
            "",
            response_box(
                "Employer associated with Alderwick | Llama 3.3 70B Instruct",
                employer_b,
                f"{score_triplet(employer_b)}; employer-associated option first",
            ),
            "",
        ]
    )

    owner_choice, alternative_choice = records["option_first_v1"]
    scenario = scenarios[owner_choice["score"]["scenario_id"]]
    lines.extend(
        [
            r"\subsection{Forced option choice: recommendation can vary without factual omission}",
            latex_escape(scenario_summary(scenario)),
            "",
            (
                r"Both models communicate all six facts with \(D=0\) and \(A=0\), yet recommend different options. These descriptive examples "
                "separate "
                "recommendation and framing from the composition of factual coverage."
            ),
            "",
            response_box(
                f"Recommends institution-associated express route | {MODEL_LABELS[owner_choice['score']['model_slug']]}",
                owner_choice,
                f"{score_triplet(owner_choice)}; institution-supporting framing and recommendation",
            ),
            "",
            response_box(
                f"Recommends alternative standard route | {MODEL_LABELS[alternative_choice['score']['model_slug']]}",
                alternative_choice,
                f"{score_triplet(alternative_choice)}; countervailing framing and recommendation",
            ),
            "",
        ]
    )

    control, commercial = records["commercial_interest_instruction_v1"]
    scenario = scenarios[control["score"]["scenario_id"]]
    lines.extend(
        [
            r"\subsection{Commercial objective: the selected direction changes at exact k=2}",
            r"\label{app:worked_pair}",
            latex_escape(scenario_summary(scenario)),
            "",
            (
                r"The scenario instance, GPT-5.4 model, frustrated customer-state cue, fact order, word budget and exact \(k=2\) task are fixed. "
                "The only experimental difference is the commercial-interest sentence. The control selects two countervailing facts; the treatment "
                "selects two institution-supporting facts. Coverage and absolute imbalance are unchanged."
            ),
            "",
            response_box(
                "Control | exact k=2 | GPT-5.4",
                control,
                f"selected {selected_ids(control)}; {score_triplet(control)}; balanced framing; no recommendation",
            ),
            "",
            response_box(
                "Commercial objective | exact k=2 | GPT-5.4",
                commercial,
                (f"selected {selected_ids(commercial)}; {score_triplet(commercial)}; institution-supporting framing and recommendation"),
            ),
            "",
            (
                "This pair demonstrates the response-level calculation rather than representing the average treatment effect. Its "
                r"treatment-minus-control change is \(4/3\) in both declared-selection and prose \(D\), while \(A=2/3\), \(T=1/3\) and "
                "conditional anchor retention remain fixed."
            ),
        ]
    )
    return "\n".join(lines)


def main() -> None:
    """Generate all stable appendix evidence assets and LaTeX inclusions."""
    ASSET_DIRECTORY.mkdir(parents=True, exist_ok=True)
    scenarios = load_scenarios()
    destination = ASSET_DIRECTORY / f"appendix_scenario_{SEED_EXAMPLE_ID.lower()}.pdf"
    render_scenario_figure(scenarios[SEED_EXAMPLE_ID], destination)

    seed = load_seed(SEED_EXAMPLE_ID)
    seed_and_scenarios = seed_example_tex(seed) + "\n\n" + scenario_examples_tex(scenarios)
    (OUTPUT_DIRECTORY / "appendix_seed_and_scenarios_generated.tex").write_text(seed_and_scenarios + "\n", encoding="utf-8")

    records = get_records()
    responses = response_examples_tex(records, scenarios)
    (OUTPUT_DIRECTORY / "appendix_response_examples_generated.tex").write_text(responses + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
