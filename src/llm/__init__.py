"""Role-scoped OpenRouter adapters used only after explicit paid-call gates."""

from src.llm.openrouter import OpenRouterClient, ProviderTextResponse

__all__ = ["OpenRouterClient", "ProviderTextResponse"]
