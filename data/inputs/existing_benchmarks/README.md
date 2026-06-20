# Existing Benchmark Inputs

Downloaded/updated and pruned on 2026-06-20 after checking `docs/RESEARCH_PLAN_V5.md` and `docs/ai-safety-reading-list-v2.xlsx`.

These inputs are for scenario inspiration only. They should not be treated as final dissertation benchmark data without checking each source license and adapting prompts to the material-risk disclosure framework.

The folders below are curated data snapshots, not full repository clones. Code, notebooks, PDFs, package files, generated figures, model caches, and nested git metadata were removed unless they were necessary to understand the retained data.

## Curated Benchmarks

| Local directory | Source | Useful local files | Notes |
|---|---|---|---|
| `deceptionbench/` | GitHub: `Aries-iai/DeceptionBench`; Hugging Face: `skyai798/DeceptionBench` | `data/economy.json`; `data/*.json`; `readme.md` | Core plan source. Retained scenario JSON only: 150 scenarios across five domains, including 30 economy scenarios. |
| `finance_agent_benchmark/` | GitHub: `vals-ai/finance-agent` | `data/public.csv`; `data/public.txt`; `README.md` | Core plan source. Public local subset has 50 finance research questions; full hosted suite appears gated through Vals. |
| `financebench/` | GitHub: `patronus-ai/financebench` | `data/financebench_open_source.jsonl`; `data/financebench_document_information.jsonl`; `README.md` | Newly added finance QA source. Retained 150 open-source annotated QA cases and 361 document metadata rows; PDFs and model result files were pruned. |
| `finmcp_bench/` | GitHub: `aliyun/qwen-dianjin`; Hugging Face: `DianJin/FinMCP-Bench` | `huggingface_dataset/test/benchmark_all.json`; `benchmark_single_tool.json`; `benchmark_multi_tool.json`; `benchmark_multi_turn.json`; `README.md` | Core plan source. Retained HF test JSON: 613 samples, split into 145 single-tool, 249 multi-tool, and 219 multi-turn samples. |
| `finsafetybench/` | GitHub: `sustech-nlp/FinSafetyBench` | `data/FinsafetyBenchmark.csv`; `README.md` | Core plan source. Local CSV has 1,881 bilingual financial crime and professional-ethics prompts. |
| `finvault/` | GitHub: `aifinlab/FinVault` | `sandbox/attack_datasets/`; `sandbox/normal_datasets/`; `sandbox/attack_datasets_synthesis/`; `DATASET_CARD.md` | Finance-native adjacent source from the sheet. Release card reports 31 sandbox environments, 107 attack cases, 107 normal cases, and 856 synthesized attacks. |
| `liars_bench/` | GitHub: `Cadenza-Labs/liars-bench`; Hugging Face: `Cadenza-Labs/liars-bench` | `results/subsets/insider-trading.csv`; `results/subsets/*.csv`; `README.md` | Newly added detection-methodology source. Retained normalized generated scenario CSVs only; detector outputs and intermediate rollout caches were pruned. The separate HF parquet dataset is public but gated behind logged-in contact-info acceptance, so it was not cloned anonymously. |
| `agent_safetybench/` | GitHub: `thu-coai/Agent-SafetyBench` | `data/released_data.json`; `environments/`; `README.md` | Adjacent risk-awareness/tool-use inspiration from the sheet. Local JSON has 2,000 test cases. |
| `toolemu/` | GitHub: `ryoungj/ToolEmu` | `assets/all_cases.json`; `assets/all_toolkits.json`; `assets/README.md` | Adjacent tool-use inspiration from the sheet. Local assets include 144 test cases and 38 toolkits. |
| `convfinqa/` | GitHub: `czyssrs/ConvFinQA` | `data/train.json`; `data/dev.json`; `data/train_turn_sample_500.json`; `data/dev_turn.json`; `data/test_private.json`; `data/test_turn_private.json`; `README.md` | Adjacent finance-task source from the sheet. Retained extracted split JSONs only; original zip and code were pruned. The full `train_turn.json` was replaced with a deterministic 500-record sample because the source file exceeded GitHub's 100 MB file limit. |

## Checked But Not Downloaded

| Benchmark | Reason |
|---|---|
| Risk Concealment / CoRT / FIN-Bench | The public GitHub repo `gcheng128/CoRT` currently contains only a README saying the code and data will be released after internal review. |
| JANUS | The arXiv abstract says the corpus and code are public, but no direct downloadable repository or dataset link was discoverable during this pass. |
| FinBen / PIXIU | Public resources exist, but the benchmark is a broad multi-dataset suite on Hugging Face rather than a compact scenario source. Not downloaded in this pass to avoid pulling a large general evaluation collection. |
| SPADE-Bench | No stable public code/data download route was discoverable during this pass. |

## Quick Inventory

- After pruning, `data/inputs/existing_benchmarks/` is about 452 MB total.
- Largest retained folders are Liars' Bench (~134 MB normalized subset CSVs), FinMCP-Bench (~69 MB test JSONs), and ConvFinQA (~113 MB after replacing the oversized train-turn split with a 500-record sample).
- No nested `.git`, `.gitmodules`, code packages, notebooks, PDFs, zip archives, package lockfiles, or Python runner files are retained in the curated benchmark snapshots.
- FinMCP Hugging Face files initially cloned as Git LFS pointers; the actual JSON blobs were fetched via direct Hugging Face `resolve/main/...` URLs before the repo was pruned to data files.
- Existing unrelated git state was not changed. `git status --short` already showed unrelated `.agents/` before this benchmark cleanup.
