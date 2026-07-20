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
  "run_unit_id", "fact_id", "pairwise_disclosure_gap", "unsupported_reassurance", "disclosure_ordinal",
  "word_budget", "emotional_cue", "integrity", "model_id", "source_order",
  "use_case_id", "scenario_id"
)
missing_columns <- setdiff(required_columns, names(data))
if (length(missing_columns) > 0) {
  stop(paste("analysis input lacks columns:", paste(missing_columns, collapse = ", ")))
}

fixed_formula <- "word_budget * emotional_cue * integrity * model_id + source_order + use_case_id + (1 | scenario_id)"
conversation_data <- data[!duplicated(data$run_unit_id), ]
lmer_model <- lme4::lmer(as.formula(paste("pairwise_disclosure_gap ~", fixed_formula)), data = conversation_data)
glmer_model <- lme4::glmer(
  as.formula(paste("unsupported_reassurance ~", fixed_formula)),
  data = conversation_data,
  family = stats::binomial()
)
data$disclosure_ordinal <- ordered(data$disclosure_ordinal)
clmm_model <- ordinal::clmm(as.formula(paste("disclosure_ordinal ~", fixed_formula)), data = data)

lmer_messages <- lmer_model@optinfo$conv$lme4$messages
glmer_messages <- glmer_model@optinfo$conv$lme4$messages
clmm_messages <- clmm_model$optRes$message
messages <- as.character(na.omit(c(lmer_messages, glmer_messages, clmm_messages)))
converged <- length(messages) == 0 && isTRUE(clmm_model$convergence == 0)

lmer_coefficients <- stats::coef(summary(lmer_model))
glmer_coefficients <- stats::coef(summary(glmer_model))
clmm_coefficients <- stats::coef(summary(clmm_model))
estimands <- c(
  lmer_word_budget = unname(lmer_coefficients[grep("word_budget", rownames(lmer_coefficients))[1], "Estimate"]),
  glmer_word_budget = unname(glmer_coefficients[grep("word_budget", rownames(glmer_coefficients))[1], "Estimate"]),
  clmm_word_budget = unname(clmm_coefficients[grep("word_budget", rownames(clmm_coefficients))[1], "Estimate"])
)

summary_payload <- list(
  schema_version = "1.0.0",
  analysis_id = "risk_comm_v1_mixed_models",
  engine = "r",
  method = "lmer_glmer_clmm_robustness",
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
