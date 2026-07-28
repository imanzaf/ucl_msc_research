#!/usr/bin/env Rscript

set.seed(7)
design <- expand.grid(
  use_case_id = sprintf("CF%03d", 1:10),
  replication = 1:2,
  model_id = c("m1", "m2", "m3"),
  source_order = "A",
  word_budget = c("ample", "tight"),
  emotional_cue = c("neutral", "worried"),
  integrity = c("absent", "targeted"),
  fact_index = 1:4,
  stringsAsFactors = FALSE
)
design$scenario_id <- paste0(design$use_case_id, "_R", design$replication)
design$run_unit_id <- with(
  design,
  paste(scenario_id, model_id, source_order, word_budget, emotional_cue, integrity, sep = "__")
)
design$fact_id <- paste0(design$scenario_id, "_F", design$fact_index)
latent <-
  ifelse(design$word_budget == "tight", -0.6, 0) +
  ifelse(design$emotional_cue == "worried", -0.3, 0) +
  ifelse(design$integrity == "targeted", 0.4, 0) +
  stats::rnorm(nrow(design), sd = 0.8)
design$fact_present <- as.integer(latent > 0)
design$pair_id <- paste0(design$scenario_id, "_P", ifelse(design$fact_index <= 2, 1, 2))
design$decision_alignment <- ifelse(design$fact_index %in% c(1, 4), "owner_supporting", "owner_countervailing")
design$selective_communication_score <- pmin(
  pmax(0.35 + ifelse(design$word_budget == "tight", 0.15, 0) + stats::rnorm(nrow(design), sd = 0.1), 0),
  1
)
design$word_budget <- ifelse(design$word_budget == "tight", "concise", "baseline")
design$expressed_concern <- ifelse(design$emotional_cue == "worried", "concerned", "neutral")

input_path <- tempfile(fileext = ".csv")
output_path <- tempfile(fileext = ".json")
utils::write.csv(design, input_path, row.names = FALSE)
status <- system2(
  "Rscript",
  c("run_mixed_models.R", input_path, output_path, paste(rep("0", 64), collapse = ""))
)
if (status != 0 || !file.exists(output_path)) {
  stop("locked R robustness smoke fit failed")
}
summary <- jsonlite::read_json(output_path, simplifyVector = TRUE)
if (!all(c("selective_word_budget", "binary_fact_word_budget") %in% names(summary$estimands))) {
  stop("locked R robustness smoke fit omitted a required model")
}
cat("Locked selective-score lmer and binary-fact glmer smoke fit completed.\n")
