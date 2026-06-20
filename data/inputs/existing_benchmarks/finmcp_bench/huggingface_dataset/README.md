---
license: cc-by-nc-sa-4.0
---
## Fin-MCP

<div align="center">
  <img alt="image" src="https://raw.githubusercontent.com/aliyun/qwen-dianjin/refs/heads/master/images/dianjin_logo.png">
  <p align="center">
        💜 <a href="https://tongyi.aliyun.com/dianjin">Qwen DianJin Platform</a>  |
        🤗 <a href="https://huggingface.co/DianJin">HuggingFace</a>  |
        🤖 <a href="https://github.com/aliyun/qwen-dianjin">Github</a> 
    </p>
</div>

### Introduction
We propose FinMCP-Bench, a comprehensive benchmark for
evaluating LLMs’ ability to invoke MCP tools in financial
scenarios. It contains 613 samples across 10 main scenar-
ios and 33 sub-scenarios, including real and synthetic user
queries, with three sample types: single tool, multi-tool, and multi-turn, allowing evaluation across different levels of task complexity.


The **10 main scenarios** and **33 sub-scenarios** are illustrated in the following figure:
![Scenarios Show](fig/category.png)


#### Single-Tool
Single-tool: resolved with a single tool call in one conversa-
tional turn (145 samples).


#### Multi-tool 
Multi-tool: involves multiple tool calls within a single con-
versational turn, which may be sequential or parallel (249
samples).

#### Multi-turn
Multi-turn: spans multiple conversational turns, each poten-
tially invoking one or more tools (219 samples).

#### MCP-All
ALL: includes all three sample types (613 samples).


* The MCP tools are from Qieman. You can obtain the MCP Server URL and MCP_SCHEMA from the [qieman](https://qieman.com/) , [qieman MCP Tools](https://qieman.com/mcp/tools)