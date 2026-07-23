#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) {
  stop("usage: run_mixed_models.R <input.csv> <output.json> <input_sha256>")
}

if (!requireNamespace("renv", quietly = TRUE)) {
  stop("renv is required; restore analysis/r/renv.lock before analysis")
}
renv::load(project = ".")

required_packages <- c("jsonlite", "lme4", "ordinal")
missing_packages <- required_packages[!vapply(required_packages, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing_packages) > 0) {
  stop(paste("missing renv packages:", paste(missing_packages, collapse = ", ")))
}

input_path <- args[[1]]
output_path <- args[[2]]
input_sha256 <- args[[3]]
data <- read.csv(input_path, stringsAsFactors = TRUE)

required_columns <- c(
  "run_unit_id", "fact_id", "pair_id", "selective_risk_communication_score", "disclosure_ordinal",
  "word_budget", "expressed_concern", "cue_template_id", "model_id", "use_case_id", "scenario_id"
)
missing_columns <- setdiff(required_columns, names(data))
if (length(missing_columns) > 0) {
  stop(paste("analysis input lacks columns:", paste(missing_columns, collapse = ", ")))
}

data$word_budget <- factor(data$word_budget, levels = c("ample", "tight"))
data$expressed_concern <- factor(data$expressed_concern, levels = c("neutral", "concerned"))
data$cue_template_id <- factor(data$cue_template_id)
fixed_terms <- "word_budget * expressed_concern + expressed_concern * cue_template_id + model_id + use_case_id"
random_terms <- "(1 | scenario_id) + (1 | pair_id) + (1 | fact_id)"
lmer_model <- lme4::lmer(
  as.formula(paste("selective_risk_communication_score ~", fixed_terms, "+", random_terms)),
  data = data
)
data$disclosure_ordinal <- ordered(data$disclosure_ordinal)
clmm_model <- ordinal::clmm(
  as.formula(paste("disclosure_ordinal ~ fact_valence +", fixed_terms, "+", random_terms)),
  data = data
)

lmer_messages <- lmer_model@optinfo$conv$lme4$messages
clmm_messages <- clmm_model$optRes$message
messages <- as.character(na.omit(c(lmer_messages, clmm_messages)))
converged <- length(messages) == 0 && isTRUE(clmm_model$convergence == 0)

lmer_coefficients <- stats::coef(summary(lmer_model))
clmm_coefficients <- stats::coef(summary(clmm_model))
estimands <- c(
  composite_word_budget = unname(lmer_coefficients["word_budgettight", "Estimate"]),
  composite_expressed_concern = unname(lmer_coefficients["expressed_concernconcerned", "Estimate"]),
  ordinal_word_budget = unname(clmm_coefficients["word_budgettight", "Estimate"]),
  ordinal_expressed_concern = unname(clmm_coefficients["expressed_concernconcerned", "Estimate"])
)

summary_payload <- list(
  schema_version = "2.0.0",
  analysis_id = "risk_comm_v1_mixed_models",
  engine = "r",
  method = "composite_lmer_and_fact_clmm_with_template_pair_fact_scenario_effects",
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
