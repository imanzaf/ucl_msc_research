# FinVault Dataset Card

FinVault is an anonymized benchmark package for evaluating financial agent safety in execution-grounded environments. The dataset is designed to test whether tool-using agents preserve business controls when facing adversarial prompts and legitimate financial requests.

## Summary

| Field | Value |
|:---|:---|
| Release type | Anonymized public research artifact |
| Domains | credit, insurance, securities, payment, AML/compliance, risk management |
| Sandbox environments | 31 |
| Attack cases | 107 |
| Normal cases | 107 |
| Synthesized attacks | 856 |
| JSON dataset files | 310 |
| Evaluation style | execution-grounded state verification |

## Dataset Components

| Directory | Files | Purpose |
|:---|---:|:---|
| `sandbox/attack_datasets/` | 31 | Core attack cases for each financial scenario |
| `sandbox/normal_datasets/` | 31 | Legitimate business requests for utility and over-refusal checks |
| `sandbox/attack_datasets_synthesis/` | 248 | Eight synthesized attack families across all scenarios |
| `sandbox/sandbox_00` to `sandbox/sandbox_30` | 31 directories | Tool, state, environment, reward, and vulnerability code |
| `finvault_dataset/` | 4 Python files | Lightweight loading, validation, and privacy helpers |
| `scripts/` and `tests/` | 2 Python files | Release integrity and privacy checks |

## Scenario Coverage

| Financial Domain | # Scenarios | Example Workflows |
|:---|---:|:---|
| Credit & Lending | 7 | loan approval, supply-chain finance, mortgage review |
| Insurance | 4 | claims review, product sales, agent management |
| Securities & Investment | 5 | investment advisory, fund sales, disclosure checks |
| Payment & Settlement | 4 | cross-border payment, merchant onboarding, FX settlement |
| Compliance & AML | 6 | due diligence, suspicious transaction review, tax compliance |
| Risk Management | 5 | valuation, ABS rating, ESG assessment, internal audit |

## Synthesized Attack Families

| Attack Family | Files | Cases |
|:---|---:|---:|
| Authority impersonation | 31 | 107 |
| Direct JSON injection | 31 | 107 |
| Emotional manipulation | 31 | 107 |
| Encoding disguise | 31 | 107 |
| Gradual induction | 31 | 107 |
| Hypothetical scenario | 31 | 107 |
| Instruction override | 31 | 107 |
| Roleplay induction | 31 | 107 |

## Anonymization

The release replaces or removes obvious private values, including:

- person names
- organization names
- locations and facilities
- phone numbers and email addresses
- identity numbers
- customer, account, user, employee, policy, document, and case identifiers
- URLs and account-like identifiers found in printable Base64 payloads

The original-to-placeholder mapping is not included because that mapping would itself be sensitive.

## Excluded Content

This public package intentionally excludes:

- original non-anonymized data
- `.env` files and API credentials
- model outputs, logs, and generated result folders
- paper source files, PDFs, review materials, and build artifacts
- private working notes and reference folders

## Validation

Run the release checks from the repository root:

```bash
python scripts/check_release.py
python -m unittest discover -s tests
python -m py_compile sandbox/run_attack_test.py sandbox/run_llama_guard3_test.py sandbox/run_llama_guard4_test.py sandbox/run_gpt_oss_safeguard_test.py sandbox/defense_evaluation.py
```

Expected integrity-check output:

```json
{
  "status": "ok",
  "dataset_json_files": 310
}
```

## Intended Use

FinVault is intended for research on financial-agent safety, execution-grounded evaluation, adversarial prompting, tool-use risk, and safeguard comparison. It is not intended for production financial decision-making or for reconstructing private source data.
