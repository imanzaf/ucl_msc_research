#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) {
  stop("usage: run_mixed_models.R <input.csv> <output.json> <input_sha256>")
}

if (!requireNamespace("renv", quietly = TRUE)) {
  stop("renv is required; restore analysis/r/renv.lock before analysis")
}
renv::load(project = ".")

required_packages <- c("jsonlite", "lme4")
missing_packages <- required_packages[!vapply(required_packages, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing_packages) > 0) {
  stop(paste("missing renv packages:", paste(missing_packages, collapse = ", ")))
}

input_path <- args[[1]]
output_path <- args[[2]]
input_sha256 <- args[[3]]
data <- read.csv(input_path, stringsAsFactors = TRUE)

required_columns <- c(
  "run_unit_id", "fact_id", "pair_id", "selective_communication_score", "fact_present",
  "decision_alignment", "word_budget", "expressed_concern", "model_id", "use_case_id", "scenario_id"
)
missing_columns <- setdiff(required_columns, names(data))
if (length(missing_columns) > 0) {
  stop(paste("analysis input lacks columns:", paste(missing_columns, collapse = ", ")))
}

data$word_budget <- factor(data$word_budget, levels = c("baseline", "concise"))
data$expressed_concern <- factor(data$expressed_concern, levels = c("neutral", "concerned"))
fixed_terms <- "word_budget * expressed_concern + model_id + use_case_id"
random_terms <- "(1 | scenario_id) + (1 | pair_id) + (1 | fact_id)"
lmer_model <- lme4::lmer(
  as.formula(paste("selective_communication_score ~", fixed_terms, "+", random_terms)),
  data = data
)
glmer_model <- lme4::glmer(
  as.formula(paste("fact_present ~ decision_alignment +", fixed_terms, "+", random_terms)),
  data = data,
  family = stats::binomial()
)

lmer_messages <- lmer_model@optinfo$conv$lme4$messages
glmer_messages <- glmer_model@optinfo$conv$lme4$messages
messages <- as.character(na.omit(c(lmer_messages, glmer_messages)))
converged <- length(messages) == 0

lmer_coefficients <- stats::coef(summary(lmer_model))
glmer_coefficients <- stats::coef(summary(glmer_model))
estimands <- c(
  selective_word_budget = unname(lmer_coefficients["word_budgetconcise", "Estimate"]),
  selective_expressed_concern = unname(lmer_coefficients["expressed_concernconcerned", "Estimate"]),
  binary_fact_word_budget = unname(glmer_coefficients["word_budgetconcise", "Estimate"]),
  binary_fact_expressed_concern = unname(glmer_coefficients["expressed_concernconcerned", "Estimate"])
)

summary_payload <- list(
  schema_version = "2.0.0",
  analysis_id = "risk_comm_v1_mixed_models",
  engine = "r",
  method = "selective_score_lmer_and_binary_fact_glmer_with_pair_fact_scenario_effects",
  estimands = as.list(estimands),
  confidence_intervals = list(),
  raw_p_values = list(),
  adjusted_p_values = list(),
  converged = converged,
  convergence_messages = unname(messages),
  source_data_sha256 = input_sha256,
  generated_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
)
jsonlite::write_json(summary_payload, output_path, auto_unbox = TRUE, pretty = TRUE)
