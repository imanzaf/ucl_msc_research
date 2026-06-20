# FinSafetyBench


## News

- **[2026.04]** 🎉 This paper has been accepted to the **ACL 2026 Findings**!

## Overview
**FinSafetyBench** is a bilingual (English / Chinese) red-teaming benchmark for financial safety. It is designed to evaluate LLM refusal and defense behavior on realistic financial crime and ethics violation prompts. The dataset combines self-constructed cases and curated external samples for research on jailbreak testing, cross-lingual robustness, and defensive methods.

## 📊 Benchmark Framework

### Taxonomy of Financial Violations
The dataset encompasses 14 fine-grained subcategories across financial crimes and professional-ethics violations. 

<p align="center">
  <img src="picture/category.png" width="600" alt="Taxonomy of FinSafetyBench">
</p>


### Data Construction Pipeline
FinSafetyBench is built upon real-world case collections, data filtering, harmful instruction generation, external expansion, and bilingual alignment. 

![Data Construction Pipeline](picture/FinBench.png) 

## 📈 Main Results
While general-purpose LLMs maintain near-zero baseline ASRs under direct non-jailbroken queries (with the exception of the finance-specific model XuanYuan), they demonstrate significant vulnerability when evaluated against three representative jailbreak attacks ([PAIR](https://github.com/patrickrchao/JailbreakingLLMs), [ReNeLLM](https://github.com/NJUNLP/ReNeLLM), [FlipAttack](https://github.com/yueliu1999/FlipAttack)). The implementations of these attacks closely follow their official source codes, with the jailbreak prompts natively adapted to Chinese when evaluated on the Chinese dataset. The table below shows the average Attack Success Rate (ASR%). 

| Target Model | Attack Method | Financial Crimes (En) | Financial Crimes (Zh) | Ethical Violations (En) | Ethical Violations (Zh) |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **LLaMA-3** <br>*(Meta-Llama-3-8B-Instruct)* | PAIR <br> ReNeLLM <br> FlipAttack <br> **Average** | 34.79 <br> 32.91 <br> 29.16 <br> **32.29** | 78.58 <br> 39.72 <br> 39.65 <br> **52.65** | 45.34 <br> 48.35 <br> 27.99 <br> **40.56** | 61.69 <br> 33.97 <br> 32.05 <br> **42.57** |
| **InternLM3** <br>*(InternLM3-8B-Instruct)* | PAIR <br> ReNeLLM <br> FlipAttack <br> **Average** | 90.74 <br> 84.94 <br> 40.88 <br> **72.18** | 80.73 <br> 77.47 <br> 36.67 <br> **64.96** | 72.83 <br> 57.16 <br> 18.17 <br> **49.39** | 63.90 <br> 44.23 <br> 32.63 <br> **46.92** |
| **GLM-4** <br>*(GLM-4-9B-0414)* | PAIR <br> ReNeLLM <br> FlipAttack <br> **Average** | 90.52 <br> 92.00 <br> 34.51 <br> **72.34** | 90.11 <br> 93.77 <br> 77.19 <br> **87.02** | 71.31 <br> 79.40 <br> 20.02 <br> **56.91** | 75.78 <br> 73.21 <br> 35.76 <br> **61.59** |
| **Mistral** <br>*(Mistral-Small-24B-Instruct-2501)* | PAIR <br> ReNeLLM <br> FlipAttack <br> **Average** | 94.53 <br> 92.81 <br> 93.32 <br> **93.55** | 93.87 <br> 88.34 <br> 92.15 <br> **91.46** | 81.71 <br> 86.15 <br> 68.97 <br> **78.95** | 77.37 <br> 70.64 <br> 64.60 <br> **70.87** |
| **Qwen2.5** <br>*(Qwen2.5-32B-Instruct)* | PAIR <br> ReNeLLM <br> FlipAttack <br> **Average** | 92.12 <br> 79.36 <br> 93.06 <br> **88.18** | 81.65 <br> 68.21 <br> 92.33 <br> **80.73** | 72.03 <br> 72.66 <br> 71.34 <br> **72.01** | 67.85 <br> 60.16 <br> 68.58 <br> **65.53** |
| **XuanYuan** <br>*(XuanYuan-13B-Chat)* | PAIR <br> ReNeLLM <br> FlipAttack <br> **Average** | 89.76 <br> 76.14 <br> 6.52 <br> **57.47** | 92.12 <br> 71.21 <br> 45.39 <br> **69.58** | 72.34 <br> 50.70 <br> 12.15 <br> **45.06** | 75.14 <br> 36.66 <br> 33.75 <br> **48.52** |

*(Higher ASR indicates the model is more vulnerable to the corresponding attack)*

## Data file
**Path:** `data/FinsafetyBenchmark.csv`  
**CSV columns:** `id, question_en, category_en, question_zh, category_zh, source`

## Size & provenance
- **Total samples:** 1881 (1201 self-constructed + 680 external)  
- **Languages:** Chinese ⇄ English aligned pairs  
- **Categories:** 14 fine-grained subcategories across financial crime and professional-ethics violations

## Evaluation Script (judge.py)

The `judge.py` script is used to automatically evaluate model responses on the benchmark. It combines keyword dictionary detection and a scoring mechanism based on a Judge LLM (e.g., Qwen3-32B) to provide a quantitative score (1-10) assessing whether the response contains illegal information or exhibits jailbreak behavior.

**Usage:**

1.  **Configure Environment:** Ensure your Judge LLM service is running and necessary environment variables (such as `DEEPINFRA_API_KEY`) are set.
2.  **Prepare Input:** Prepare a JSONL file where each line contains the `question` (prompt) and the model `output` (response) fields to be evaluated.
3.  **Run Evaluation:** Execute the following Python command to start the evaluation process:

    ```bash
    python judge.py
    ```

    *Note: You may need to modify the configuration variables in the `if __name__ == '__main__':` block at the end of the `judge.py` script according to your actual input/output filenames and Judge LLM Model ID.*

---

## Citation

If you use the FinSafetyBench or find our work useful, please cite our paper:

```bibtex
@misc{hou2026finsafetybenchevaluatingllmsafety,
      title={FinSafetyBench: Evaluating LLM Safety in Real-World Financial Scenarios}, 
      author={Yutao Hou and Yihan Jiang and Yuhan Xie and Jian Yang and Liwen Zhang and Hailiang Huang and Guanhua Chen and Yun Chen},
      year={2026},
      eprint={2605.00706},
      archivePrefix={arXiv},
      primaryClass={cs.CL},
      url={https://arxiv.org/abs/2605.00706}, 
}
```

